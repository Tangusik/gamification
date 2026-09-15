/** Провайдер состояния авторизации и активного учреждения. */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import * as authApi from '../api/auth'
import type { Membership, User } from '../api/auth'
import {
  bumpSessionGeneration,
  getSessionGeneration,
  refreshAccessToken,
  runUnderRefreshLock,
  setApiErrorHandlers,
  setRefreshHandler,
} from '../api/client'
import { ApiError, REFRESH_TOKEN_INVALID } from '../api/errors'
import { ScreenState } from '../components/ScreenState'
import { AuthContext, type AuthStatus, type AuthValue, type InstitutionContext } from './authContext'
import { decodeInstitutionId, decodeUserId } from './claims'
import * as tokenStorage from './tokenStorage'

type Props = {
  children: ReactNode
  /** Что делать при 403 `INSTITUTION_CONTEXT_REQUIRED`; подключает роутер. */
  onInstitutionContextRequired?: () => void
}

/**
 * Сообщения между вкладками: выход и вход (У9/риск 1 плана `10-refresh.md`).
 * `login` несёт `userId` (К2): вкладка, уже авторизованная другим
 * пользователем, должна отличить «вошёл я же в соседней вкладке» (ничего не
 * делать) от «вошёл другой пользователь по этой же cookie» (перезапустить
 * старт, а не смешивать чужие данные со своими).
 */
type AuthBroadcastMessage = { type: 'logout' } | { type: 'login'; userId: string }
const AUTH_BROADCAST_CHANNEL = 'gamification-auth'

export function AuthProvider({ children, onInstitutionContextRequired }: Props) {
  // Access больше не переживает перезагрузку (У9): единственный способ узнать
  // стартовое состояние — запросить `refresh` по cookie, поэтому старт всегда
  // с `loading`, а не с чтения хранилища.
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)
  /** Сетевая ошибка стартового `refresh` — для экрана «Повторить». */
  const [startupError, setStartupError] = useState<unknown>(null)
  const [bootstrapAttempt, setBootstrapAttempt] = useState(0)

  const [memberships, setMemberships] = useState<Membership[] | null>(null)
  const [membershipsError, setMembershipsError] = useState<unknown>(null)
  const [membershipsAttempt, setMembershipsAttempt] = useState(0)

  const statusRef = useRef(status)
  useEffect(() => {
    statusRef.current = status
  }, [status])

  // Ref, а не замыкание на `user` (К2 плана `10-refresh.md`): `performRefresh`
  // регистрируется в `client.ts` один раз (см. эффект ниже) и должен видеть
  // актуального пользователя на момент каждого вызова, а не того, что был на
  // момент подписки.
  const userRef = useRef(user)
  useEffect(() => {
    userRef.current = user
  }, [user])

  const channelRef = useRef<BroadcastChannel | null>(null)

  /**
   * Локальный выход: чистим токен и переводим приложение в аноним.
   *
   * Увеличивает поколение сессии (К6): пока не вернулся ответ на `refresh`
   * или обычный запрос, ушедший ещё при прежней сессии, погасить эту, уже
   * новую (анонимную или следующую авторизованную), он не должен.
   */
  const forgetSession = useCallback(() => {
    bumpSessionGeneration()
    tokenStorage.clear()
    setToken(null)
    setUser(null)
    setStatus('anon')
    setMemberships(null)
    setMembershipsError(null)
  }, [])

  // Обработчики общих ошибок транспорта. 401 = токена больше нет.
  useEffect(() => {
    setApiErrorHandlers({
      onUnauthorized: forgetSession,
      onInstitutionContextRequired,
    })
    return () => setApiErrorHandlers({})
  }, [forgetSession, onInstitutionContextRequired])

  // Единственный источник нового access-токена для `client.ts`: сетевой вызов
  // делает `POST …/jwt/refresh` по refresh-cookie, `institution_id` — из
  // последнего выбора (вопрос 1 плана `10-refresh.md`, поле пустое — сервер
  // сам возьмёт то, что уже запомнено в сессии). Single-flight и Web Locks —
  // забота `refreshAccessToken` в `client.ts`, здесь только сам HTTP-вызов.
  const performRefresh = useCallback(async (): Promise<string> => {
    const lastInstitutionId = tokenStorage.getLastInstitutionId()
    // Поколение на момент запроса (К6): пока ждём ответ, сессия могла
    // смениться (выход, новый вход, смена пользователя в другой вкладке) —
    // тогда результат этого `refresh` принадлежит уже прошлому поколению и
    // не должен подменить токен новой сессии.
    const generationAtStart = getSessionGeneration()
    const response = await authApi.refresh(lastInstitutionId)

    if (generationAtStart !== getSessionGeneration()) {
      // Поколение уже другое — не применяем токен и не трогаем состояние.
      // Не статус 0 (К3 не повторит), не 401 (не спутается с настоящим
      // отказом refresh-токена); проверка на ~стр. 250 `client.ts` и так
      // отбросит этот результат для запроса, ушедшего в прошлом поколении.
      throw new ApiError(409, REFRESH_TOKEN_INVALID)
    }

    // Смешение пользователей во вкладке (К2): та же refresh-cookie могла за
    // это время выдать токен другого пользователя — например, в другой
    // вкладке того же браузера вышли и вошли заново на общем cookie-пути.
    // Сверяем `sub` нового access с известным пользователем через ref, а не
    // через замыкание на state (см. `userRef` выше).
    const knownUserId = userRef.current?.id ?? null
    const newUserId = decodeUserId(response.access_token)
    if (knownUserId !== null && newUserId !== null && newUserId !== knownUserId) {
      // Чужие данные уже не годятся. Внутри этого обработчика нельзя делать
      // не-`/jwt/*` запросы (`getMe` при 401 позвал бы этот же
      // `refreshInFlight` и навсегда завис бы вместе с межвкладочным замком) —
      // поэтому только сбрасываем сессию и просим bootstrap перезапуститься;
      // `getMe` для нового пользователя выполнится уже там, вне замка.
      forgetSession()
      setStatus('loading')
      setBootstrapAttempt((value) => value + 1)
      // Поколение уже сменилось в `forgetSession` — тот же не-0/не-401-
      // текущего-поколения код, что и выше.
      throw new ApiError(409, REFRESH_TOKEN_INVALID)
    }

    tokenStorage.set(response.access_token)
    setToken(response.access_token)
    return response.access_token
  }, [forgetSession])

  useEffect(() => {
    setRefreshHandler(performRefresh)
    return () => setRefreshHandler(null)
  }, [performRefresh])

  // Старт приложения (и его ретрай) — обновление по cookie, а не чтение
  // сохранённого токена. 401 чистит сессию через общий `onUnauthorized`
  // (эффект выше уже подключён к этому моменту), сеть — экран «Повторить».
  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        const access = await refreshAccessToken()
        if (cancelled) return
        const me = await authApi.getMe(access)
        if (cancelled) return
        setUser(me)
        setStatus('authed')
      } catch (caught) {
        if (cancelled) return
        if (caught instanceof ApiError && caught.status === 401) {
          // Уже обработано перехватчиком `client.ts` → `onUnauthorized` →
          // `forgetSession`: статус уже `anon`, трогать больше нечего.
          return
        }
        setStatus('error')
        setStartupError(caught)
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [bootstrapAttempt])

  const retryBootstrap = useCallback(() => {
    // Состояние переводится в `loading` здесь, а не эффектом: это реакция на
    // клик, а не синхронизация с внешней системой (oxlint `set-state-in-effect`).
    setStatus('loading')
    setStartupError(null)
    setBootstrapAttempt((value) => value + 1)
  }, [])

  // Синхронизация между вкладками через `BroadcastChannel` (риск 1 плана
  // `10-refresh.md`): `storage` для этого не подходит — access больше не
  // лежит в `localStorage`. Выход в одной вкладке гасит остальные; вход в
  // одной вкладке — повод анонимным соседям попробовать `refresh`: cookie
  // уже рабочая.
  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return

    const channel = new BroadcastChannel(AUTH_BROADCAST_CHANNEL)
    channelRef.current = channel
    channel.onmessage = (event: MessageEvent<AuthBroadcastMessage>) => {
      if (event.data.type === 'logout') {
        forgetSession()
      } else if (event.data.type === 'login') {
        const sameUser = userRef.current?.id === event.data.userId
        if (statusRef.current === 'authed' && !sameUser) {
          // Другая вкладка вошла другим пользователем по той же cookie
          // (К2): текущие данные больше не годятся — сброс и перезапуск
          // старта для нового пользователя. `loading`, а не `anon`
          // (`forgetSession` сама ставит `anon`): роутер не должен на миг
          // увести на логин, пока bootstrap уже перезапускается.
          forgetSession()
          setStatus('loading')
          setBootstrapAttempt((value) => value + 1)
        } else if (statusRef.current !== 'authed') {
          setBootstrapAttempt((value) => value + 1)
        }
        // `authed` и тот же пользователь — сессия уже актуальна, ничего не
        // делаем (поведение как раньше).
      }
    }
    return () => {
      channel.close()
      channelRef.current = null
    }
  }, [forgetSession])

  const applyToken = useCallback(async (issued: string) => {
    // Сначала проверяем токен запросом и только потом фиксируем его в
    // состоянии: иначе сбой getMe (не 401 — сеть, таймаут) оставит
    // приложение в промежуточном состоянии.
    const me = await authApi.getMe(issued)
    // Новый вход — новое поколение сессии (К6): результат `refresh` или
    // запроса, ушедшего ещё при прежней сессии этой вкладки, больше не
    // должен её тронуть.
    bumpSessionGeneration()
    tokenStorage.set(issued)
    setToken(issued)
    setUser(me)
    setStatus('authed')
    channelRef.current?.postMessage({ type: 'login', userId: me.id } satisfies AuthBroadcastMessage)
  }, [])

  const login = useCallback(
    async (email: string, password: string) => {
      // Под тем же межвкладочным замком, что и `refresh` (К2): вход и
      // ротация refresh-токена не должны выполняться параллельно — иначе
      // соседняя вкладка может обновиться по cookie в момент, когда она уже
      // сменилась логином. Без риска зависнуть — `runUnderRefreshLock` сам
      // `refreshAccessToken` не вызывает (см. `client.ts`).
      const response = await runUnderRefreshLock(() => authApi.login(email, password))
      await applyToken(response.access_token)
    },
    [applyToken],
  )

  const register = useCallback(
    async (email: string, password: string) => {
      await authApi.register(email, password)
      // Регистрация не выдаёт токен, поэтому сразу входим тем же паролем.
      const response = await runUnderRefreshLock(() => authApi.login(email, password))
      await applyToken(response.access_token)
    },
    [applyToken],
  )

  const logout = useCallback(async () => {
    try {
      // Cookie уходит сама; access в `Authorization` не обязателен (У10) —
      // передаём, если он есть, ради denylist, но выход работает и без него.
      // Под тем же замком, что и `refresh`/`login` (К2) — по той же причине.
      await runUnderRefreshLock(() => authApi.logout(token))
    } catch {
      // Локальный выход безусловен: сетевая ошибка не должна оставлять
      // пользователя внутри приложения.
    } finally {
      forgetSession()
      channelRef.current?.postMessage({ type: 'logout' } satisfies AuthBroadcastMessage)
    }
  }, [forgetSession, token])

  /** Обновить пользователя из ответа сервера, например после смены пароля. */
  const updateUser = useCallback((next: User) => {
    setUser(next)
  }, [])

  // Список членств — источник свежей роли и названия учреждения (claims
  // токена могут отставать от БД до 900 с). Перезагружается по требованию
  // (`reloadMemberships`) и заново при входе следующего пользователя.
  useEffect(() => {
    // Сброс при выходе — задача `forgetSession`, а не этого эффекта: он
    // вызывается из события (логаут, 401), а не молча по смене `status`.
    if (status !== 'authed' || token === null) return
    // Ошибка предыдущей попытки уже сброшена там, где начат повтор
    // (`reloadMemberships`); на первую загрузку после входа она и так `null`.
    let cancelled = false
    authApi
      .getMyInstitutions(token)
      .then((loaded) => {
        if (!cancelled) setMemberships(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setMembershipsError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [status, token, membershipsAttempt])

  const reloadMemberships = useCallback(() => {
    setMemberships(null)
    setMembershipsError(null)
    setMembershipsAttempt((value) => value + 1)
  }, [])

  /**
   * Сменить текущее учреждение. Переключает контекст токена, только если он
   * ещё не совпадает с `institutionId` — так повторный выбор того же
   * учреждения (в том числе автовыбором) не делает лишнего запроса.
   */
  const selectInstitution = useCallback(
    async (institutionId: string) => {
      const current = token
      if (current === null) return
      if (decodeInstitutionId(current) !== institutionId) {
        const response = await authApi.selectInstitution(current, institutionId)
        tokenStorage.set(response.access_token)
        setToken(response.access_token)
      }
      tokenStorage.setLastInstitutionId(institutionId)
    },
    [token],
  )

  // Автовыбор после входа и на F5 (В3/а): последнее выбранное активное
  // членство — приоритет; иначе, если активное членство ровно одно, выбор
  // очевиден. При нескольких активных или при их отсутствии выбор не
  // делается — экран `/institutions` служит и онбордингом, и выбором.
  useEffect(() => {
    if (status !== 'authed' || memberships === null || token === null) return

    const active = memberships.filter((item) => item.status === 'active')
    const lastId = tokenStorage.getLastInstitutionId()

    let target: string | null = null
    if (lastId !== null && active.some((item) => item.institution_id === lastId)) {
      target = lastId
    } else if (active.length === 1) {
      target = active[0].institution_id
    }
    if (target === null) return

    if (decodeInstitutionId(token) === target) {
      // Контекст уже верный — только фиксируем выбор для следующего раза.
      tokenStorage.setLastInstitutionId(target)
      return
    }

    // Запрос выполняется напрямую, а не через `selectInstitution`: тот же
    // API-вызов, но без промежуточного вызова функции из контекста —
    // подписка эффекта остаётся на простых значениях, без колбэка,
    // умеющего менять состояние из другого места.
    let cancelled = false
    authApi
      .selectInstitution(token, target)
      .then((response) => {
        if (cancelled) return
        tokenStorage.set(response.access_token)
        tokenStorage.setLastInstitutionId(target)
        setToken(response.access_token)
      })
      .catch(() => {
        // Автовыбор — необязательная попытка: при сбое пользователь просто
        // выбирает учреждение вручную на `/institutions`.
      })
    return () => {
      cancelled = true
    }
  }, [status, memberships, token])

  const institution = useMemo<InstitutionContext | null>(() => {
    if (token === null || memberships === null) return null
    const institutionId = decodeInstitutionId(token)
    if (institutionId === null) return null
    const membership = memberships.find(
      (item) => item.institution_id === institutionId && item.status === 'active',
    )
    if (membership === undefined) return null
    return {
      id: membership.institution_id,
      role: membership.role,
      name: membership.name,
      currencyName: membership.currency_name,
    }
  }, [token, memberships])

  const value = useMemo<AuthValue>(
    () => ({
      status,
      user,
      token,
      login,
      register,
      logout,
      updateUser,
      institution,
      memberships,
      membershipsError,
      reloadMemberships,
      selectInstitution,
    }),
    [
      status,
      user,
      token,
      login,
      register,
      logout,
      updateUser,
      institution,
      memberships,
      membershipsError,
      reloadMemberships,
      selectInstitution,
    ],
  )

  if (status === 'error') {
    // Стартовый `refresh` не дошёл до сервера — состояние авторизации
    // неизвестно, поэтому показываем не заглушку внутри layout, а отдельный
    // экран на всё приложение (риск 7 плана `10-refresh.md`: без Playwright
    // это ловится только руками).
    return (
      <main className="page page-narrow">
        <ScreenState state="error" error={startupError} onRetry={retryBootstrap} />
      </main>
    )
  }

  return <AuthContext value={value}>{children}</AuthContext>
}
