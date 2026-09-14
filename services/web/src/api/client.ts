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
import axios, { AxiosError, AxiosHeaders } from 'axios'

import { ApiError, INSTITUTION_CONTEXT_REQUIRED, NETWORK_ERROR, toApiError } from './errors'

const API_BASE = '/api/v1'

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
http.interceptors.response.use(undefined, (error: unknown) => {
  const apiError = asApiError(error)

  if (apiError.status === 401) {
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
  const { method = 'GET', json, form, token } = options

  const headers = new AxiosHeaders()
  if (token) {
    headers.setAuthorization(`Bearer ${token}`)
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
