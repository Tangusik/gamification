/**
 * Транспорт до API поверх axios.
 *
 * База — относительный `/api/v1`, константой в коде. Причин две: CORS на
 * сервисе `users` не подключён, поэтому абсолютный адрес из браузера не
 * работает в принципе; и в проде домен один — фронт и API отдаёт один и тот
 * же nginx. Это единственное место в приложении, где встречается строка базы.
 *
 * Правило путей: **никогда не слать путь с завершающим слэшем**. FastAPI
 * ответит 307 с `Location`, построенным от внутреннего пути, и через шлюз это
 * будет битый внешний адрес.
 *
 * Зачем axios, а не `fetch`: не ради асинхронности — `await` одинаков в обоих
 * случаях. Ради перехватчика ответов, в который убирается развязка общих
 * ошибок (401 и «нужен контекст учреждения»), и ради таймаута, которого у
 * `fetch` нет вовсе: без него запрос к зависшему серверу висит до таймаута
 * браузера, и пользователь смотрит на заблокированную кнопку.
 */
import axios, { AxiosError, AxiosHeaders, type InternalAxiosRequestConfig } from 'axios'

import {
  ApiError,
  INSTITUTION_CONTEXT_REQUIRED,
  NETWORK_ERROR,
  REFRESH_TOKEN_INVALID,
  toApiError,
} from './errors'

const API_BASE = '/api/v1'

/**
 * Пути `login`/`refresh`/`logout` исключены из авто-обновления и из повтора
 * запроса (Ч4 плана `10-refresh.md`): иначе 401 от самого `refresh`
 * запустил бы новый `refresh`, и так по кругу.
 */
const JWT_AUTH_PREFIX = '/users/auth/jwt/'

function isJwtAuthPath(url: string | undefined): boolean {
  return url !== undefined && url.startsWith(JWT_AUTH_PREFIX)
}

/**
 * Потолок ожидания ответа. Значение с запасом к самому долгому запросу
 * этапа — вход, где сервер считает хеш пароля (Argon2, десятки
 * миллисекунд), — но заметно меньше терпения пользователя.
 */
const REQUEST_TIMEOUT_MS = 15_000

/** Реакции на ошибки, общие для всего приложения. */
export type ApiErrorHandlers = {
  /** 401: токена нет или он погашен — чистим сессию. */
  onUnauthorized?: () => void
  /** 403 `INSTITUTION_CONTEXT_REQUIRED`: нужен выбор учреждения. */
  onInstitutionContextRequired?: () => void
}

let handlers: ApiErrorHandlers = {}

/** Подключить обработчики; вызывается один раз из приложения. */
export function setApiErrorHandlers(next: ApiErrorHandlers): void {
  handlers = next
}

/**
 * Единственный источник нового access-токена — сам делает `POST …/jwt/refresh`
 * по cookie. Регистрируется `AuthProvider`: `client.ts` не знает про
 * `src/api/auth.ts` (иначе получился бы цикл импортов), только про то, что
 * функцию обновления можно один раз подставить и дальше звать по требованию.
 */
let refreshHandler: (() => Promise<string>) | null = null

export function setRefreshHandler(next: (() => Promise<string>) | null): void {
  refreshHandler = next
}

const REFRESH_LOCK_NAME = 'gamification-refresh'

/**
 * Выполнить задачу под общим межвкладочным замком `refresh`, если Web Locks
 * доступны (без них — как есть, риск К8 плана `10-refresh.md` не чинится
 * здесь). Используется и самим `refreshAccessToken`, и `login`/`logout`
 * (К2): все три операции меняют refresh-сессию по той же cookie, и без
 * общего замка гонка между вкладками может смешать пользователей.
 *
 * Вызывать эту функцию изнутри уже взятого этого же замка нельзя — замок не
 * реентерабельный, вложенный `navigator.locks.request` с тем же именем
 * повиснет навсегда. `login`/`logout` этому правилу не угрожают: их пути
 * (`/jwt/login`, `/jwt/logout`) исключены из авто-`refresh` по 401
 * (`isJwtAuthPath`), так что задача, переданная сюда из `AuthProvider`, сама
 * `refreshAccessToken` не вызывает.
 */
export function runUnderRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  if (typeof navigator !== 'undefined' && 'locks' in navigator) {
    return navigator.locks.request(REFRESH_LOCK_NAME, () => task())
  }
  return task()
}

/** Пауза одного повтора `refresh` после сетевого отказа (К3, ниже). */
const REFRESH_NETWORK_RETRY_DELAY_MS = 1_500

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

/**
 * Выполнить сам сетевой `refresh` с одним повтором на сетевой обрыв (К3
 * плана `10-refresh.md`). Если запрос не дошёл до сервера вовсе — статус
 * ошибки `0`/`NETWORK_ERROR`, а не ответ (401/403/5xx) — сервер мог уже
 * принять его и провернуть ротацию токена; голый повтор через 1.5 с даёт
 * второй шанс уложиться в 30-секундное окно ротации. Ответ сервера (в т.ч.
 * ошибочный) не повторяется — только сетевой отказ, и только один раз.
 */
async function callRefreshHandler(handler: () => Promise<string>): Promise<string> {
  try {
    return await handler()
  } catch (error) {
    const apiError = error instanceof ApiError ? error : asApiError(error)
    if (apiError.status !== 0) {
      throw apiError
    }
    await delay(REFRESH_NETWORK_RETRY_DELAY_MS)
    return handler()
  }
}

/** Запасной single-flight в пределах вкладки — на случай отсутствия Web Locks. */
let refreshInFlight: Promise<string> | null = null

/**
 * Обновить access-токен, гарантируя, что одновременно идёт не больше одного
 * `refresh` (риск 1 плана `10-refresh.md`): между вкладками — через
 * `navigator.locks`, внутри вкладки — общий промис. Пока вкладка ждала
 * замок, cookie могла обновиться в соседней вкладке; повторный вызов
 * `refreshHandler` внутри замка от этого не страдает — каждая вкладка
 * ротирует свою пару токенов по уже актуальной cookie, а access у них свой.
 */
export function refreshAccessToken(): Promise<string> {
  if (refreshHandler === null) {
    return Promise.reject(new ApiError(401, REFRESH_TOKEN_INVALID))
  }
  if (refreshInFlight !== null) {
    return refreshInFlight
  }
  const handler = refreshHandler

  refreshInFlight = runUnderRefreshLock(() => callRefreshHandler(handler)).finally(() => {
    refreshInFlight = null
  })
  return refreshInFlight
}

/**
 * Поколение текущей сессии (К6 плана `10-refresh.md`): растёт на каждый
 * выход и на каждый новый вход/`forgetSession`. Читает и увеличивает
 * `AuthProvider` — здесь только хранилище и геттер, потому что сравнивать
 * поколение приходится прямо в перехватчике ответов, а не только в
 * провайдере.
 *
 * Смысл: если пока шёл `refresh` или обычный запрос со старым токеном
 * пользователь успел выйти и войти заново (или другая вкладка сменила
 * пользователя за той же cookie — К2), поздний ответ старого поколения не
 * должен погасить уже новую, действующую сессию и не должен подменить её
 * токен своим результатом.
 */
let sessionGeneration = 0

export function getSessionGeneration(): number {
  return sessionGeneration
}

export function bumpSessionGeneration(): number {
  sessionGeneration += 1
  return sessionGeneration
}

/**
 * Экземпляр, а не глобальный axios: перехватчик и таймаут не должны
 * навешиваться на чужие вызовы, если те когда-нибудь появятся.
 */
const http = axios.create({
  baseURL: API_BASE,
  timeout: REQUEST_TIMEOUT_MS,
  // Ответы 4xx и 5xx обязаны попадать в перехватчик ошибок, а не
  // приходить успехом: разбор в `ApiError` живёт ровно там.
  validateStatus: (status) => status >= 200 && status < 300,
})

type GenerationTaggedConfig = InternalAxiosRequestConfig & { _sessionGeneration?: number }

/**
 * Клеймо поколения сессии на момент отправки запроса (К6). Перехватчик
 * ответа сравнивает его с текущим `sessionGeneration`, чтобы поздний 401 от
 * запроса, ушедшего ещё в прошлой сессии, не погасил уже новую.
 */
http.interceptors.request.use((config) => {
  ;(config as GenerationTaggedConfig)._sessionGeneration = sessionGeneration
  return config
})

/**
 * Единственное место, где неуспешный ответ превращается в `ApiError`.
 *
 * Ветвление по HTTP-статусу, а не по тексту `detail`: код 401 сегодня
 * приходит с фразой `Unauthorized`, завтра — с `AUTH_REQUIRED`, и клиент не
 * должен от этого ломаться.
 *
 * Наружу всегда уходит `ApiError`, в том числе на сетевом отказе и таймауте.
 * Благодаря этому вызывающий код знает ровно один тип ошибки, а `instanceof
 * ApiError` в страницах остаётся исчерпывающей проверкой.
 */
http.interceptors.response.use(undefined, async (error: unknown) => {
  const apiError = asApiError(error)

  // 401 вне `/jwt/*` — кандидат на один повтор с обновлённым токеном
  // (Ч4 плана `10-refresh.md`). `/jwt/*` исключены нарочно: 401 от самого
  // `refresh` не должен запускать ещё один `refresh`.
  if (error instanceof AxiosError && apiError.status === 401 && error.config !== undefined) {
    const config = error.config as InternalAxiosRequestConfig & {
      _retriedAfterRefresh?: boolean
      _sessionGeneration?: number
    }
    if (!isJwtAuthPath(config.url) && config._retriedAfterRefresh !== true) {
      config._retriedAfterRefresh = true
      // Поколение сессии на момент, когда этот запрос решил пойти за
      // `refresh` (К6): если к моменту ответа сессия уже другая (выход,
      // новый вход, смена пользователя за той же cookie в другой вкладке),
      // ни гасить новую сессию, ни подставлять ей чужой токен нельзя.
      const requestGeneration = config._sessionGeneration ?? sessionGeneration
      let freshToken: string
      try {
        freshToken = await refreshAccessToken()
      } catch (refreshError) {
        // `refreshAccessToken()` уже отклоняется готовым `ApiError` — это
        // либо ответ `/jwt/refresh`, прошедший через этот же перехватчик,
        // либо ошибка отсутствующего `refreshHandler`. Оборачивать в
        // `asApiError` нужно, только если это неожиданно не `ApiError`.
        const refreshApiError =
          refreshError instanceof ApiError ? refreshError : asApiError(refreshError)
        if (refreshApiError.status === 401 && requestGeneration === sessionGeneration) {
          // `refresh` ответил 401 и сессия всё ещё та же, что запросила
          // обновление: токен невалиден, пользователя разлогиниваем.
          handlers.onUnauthorized?.()
        }
        // Иначе — либо `refresh` упал не из-за невалидного токена (сеть,
        // таймаут, 5xx, CSRF и т.п.), либо сессия уже сменилась, пока ждали
        // ответ: в обоих случаях `onUnauthorized` не вызываем.
        return Promise.reject(refreshApiError)
      }
      if (requestGeneration !== sessionGeneration) {
        // Сессия сменилась, пока ждали `refresh`: результат принадлежит
        // прошлому поколению и не должен подменить токен уже новой сессии
        // или повторить запрос под чужим токеном.
        return Promise.reject(apiError)
      }
      config.headers.set('Authorization', `Bearer ${freshToken}`)
      // Повтор уже прошёл через этот перехватчик: успех и ошибка приходят
      // как есть, `_retriedAfterRefresh` не даст зациклиться.
      return http.request(config)
    }
  }

  const failedRequestConfig =
    error instanceof AxiosError
      ? (error.config as GenerationTaggedConfig | undefined)
      : undefined
  const failedRequestGeneration = failedRequestConfig?._sessionGeneration ?? sessionGeneration

  if (apiError.status === 401 && failedRequestGeneration === sessionGeneration) {
    handlers.onUnauthorized?.()
  } else if (apiError.status === 403 && apiError.code === INSTITUTION_CONTEXT_REQUIRED) {
    handlers.onInstitutionContextRequired?.()
  }

  return Promise.reject(apiError)
})

/** Свести любую ошибку axios к `ApiError`. */
function asApiError(error: unknown): ApiError {
  if (!(error instanceof AxiosError)) {
    // Ошибка не из транспорта — например, дефект в самом перехватчике.
    // Гасить её нельзя, но и тип наружу должен остаться один.
    return new ApiError(0, NETWORK_ERROR)
  }
  if (error.response === undefined) {
    // Ответа нет вовсе: сеть, отменённый запрос или сработавший таймаут.
    return new ApiError(0, NETWORK_ERROR)
  }
  return toApiError(error.response.status, error.response.data)
}

export type RequestOptions = {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  /** Тело как JSON. */
  json?: unknown
  /** Тело как `application/x-www-form-urlencoded` (логин OAuth2). */
  form?: Record<string, string>
  /** Bearer-токен, если запрос идёт от имени пользователя. */
  token?: string | null
  /** Доп. заголовки для редких случаев — например, CSRF на `refresh`/`logout`. */
  headers?: Record<string, string>
}

/**
 * Выполнить запрос к API и вернуть разобранное тело.
 *
 * Успех — распарсенный JSON; для 204 — `undefined`, потому что тела там нет
 * и axios отдаёт вместо него пустую строку.
 *
 * Сигнатура сохранена с реализации на `fetch` намеренно: axios остаётся
 * деталью этого модуля, и `src/api/auth.ts` вместе со страницами о нём не
 * знают. Замена транспорта во второй раз будет стоить столько же.
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', json, form, token, headers: extraHeaders } = options

  const headers = new AxiosHeaders()
  if (token) {
    headers.setAuthorization(`Bearer ${token}`)
  }
  if (extraHeaders) {
    for (const [name, value] of Object.entries(extraHeaders)) {
      headers.set(name, value)
    }
  }

  // URLSearchParams axios сам сериализует и проставляет
  // `application/x-www-form-urlencoded`; для объекта в `json` —
  // `application/json`. Руками content-type не задаём.
  const data = form !== undefined ? new URLSearchParams(form) : json

  const response = await http.request<T>({ url: path, method, headers, data })

  if (response.status === 204) {
    return undefined as T
  }
  return response.data
}
