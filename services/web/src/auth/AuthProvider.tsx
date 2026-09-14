/** Провайдер состояния авторизации и активного учреждения. */
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'

import * as authApi from '../api/auth'
import type { Membership, User } from '../api/auth'
import { setApiErrorHandlers } from '../api/client'
import { AuthContext, type AuthStatus, type AuthValue, type InstitutionContext } from './authContext'
import { decodeInstitutionId } from './claims'
import * as tokenStorage from './tokenStorage'

type Props = {
  children: ReactNode
  /** Что делать при 403 `INSTITUTION_CONTEXT_REQUIRED`; подключает роутер. */
  onInstitutionContextRequired?: () => void
}

export function AuthProvider({ children, onInstitutionContextRequired }: Props) {
  // Токена нет — состояние известно сразу, без промежуточной проверки.
  const [status, setStatus] = useState<AuthStatus>(() =>
    tokenStorage.get() === null ? 'anon' : 'loading',
  )
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(() => tokenStorage.get())

  const [memberships, setMemberships] = useState<Membership[] | null>(null)
  const [membershipsError, setMembershipsError] = useState<unknown>(null)
  const [membershipsAttempt, setMembershipsAttempt] = useState(0)

  /** Локальный выход: чистим токен и переводим приложение в аноним. */
  const forgetSession = useCallback(() => {
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

  // Начальная проверка сохранённого токена.
  useEffect(() => {
    const saved = tokenStorage.get()
    if (saved === null) {
      // Стартовое состояние уже 'anon', делать нечего.
      return
    }

    let cancelled = false
    authApi
      .getMe(saved)
      .then((me) => {
        if (cancelled) return
        setUser(me)
        setToken(saved)
        setStatus('authed')
      })
      .catch(() => {
        if (cancelled) return
        // Любая ошибка на старте означает, что работать по этому токену
        // нельзя: 401 уже почистил сессию, остальное чистим здесь.
        forgetSession()
      })
    return () => {
      cancelled = true
    }
  }, [forgetSession])

  // Другая вкладка сменила токен или вышла: перечитываем его из хранилища.
  // Членства пересчитывать не нужно — они привязаны к пользователю, а не к
  // выбранному учреждению, набор от переключения не меняется. Исключение —
  // выход (next === null): тогда токена не осталось вовсе, и membership
  // прежнего пользователя нужно сбросить полностью через `forgetSession`,
  // иначе до перезагрузки они видны следующему, кто войдёт в этой вкладке.
  useEffect(() => {
    function onStorage() {
      const next = tokenStorage.get()
      if (next === null) {
        forgetSession()
        return
      }
      setToken((current) => (current === next ? current : next))
    }
    window.addEventListener('storage', onStorage)
    return () => window.removeEventListener('storage', onStorage)
  }, [forgetSession])

  const applyToken = useCallback(async (issued: string) => {
    // Сначала проверяем токен запросом и только потом фиксируем его в
    // хранилище и state: иначе сбой getMe (не 401 — сеть, таймаут) оставит
    // токен сохранённым при status === 'anon', и после перезагрузки
    // страницы пользователь неожиданно окажется залогинен.
    const me = await authApi.getMe(issued)
    tokenStorage.set(issued)
    setToken(issued)
    setUser(me)
    setStatus('authed')
  }, [])

  const login = useCallback(
    async (email: string, password: string) => {
      const response = await authApi.login(email, password)
      await applyToken(response.access_token)
    },
    [applyToken],
  )

  const register = useCallback(
    async (email: string, password: string) => {
      await authApi.register(email, password)
      // Регистрация не выдаёт токен, поэтому сразу входим тем же паролем.
      const response = await authApi.login(email, password)
      await applyToken(response.access_token)
    },
    [applyToken],
  )

  const logout = useCallback(async () => {
    const current = tokenStorage.get()
    try {
      if (current !== null) {
        await authApi.logout(current)
      }
    } catch {
      // Локальный выход безусловен: сетевая ошибка не должна оставлять
      // пользователя внутри приложения.
    } finally {
      forgetSession()
    }
  }, [forgetSession])

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
    return { id: membership.institution_id, role: membership.role, name: membership.name }
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

  return <AuthContext value={value}>{children}</AuthContext>
}
