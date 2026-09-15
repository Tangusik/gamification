/**
 * Контекст авторизации и хук доступа к нему.
 *
 * Вынесены из файла провайдера, чтобы в модуле с компонентом оставался только
 * компонент: так не ломается fast refresh и не срабатывает правило линтера
 * о смешанных экспортах.
 */
import { createContext, useContext } from 'react'

import type { Membership, User, UserRole } from '../api/auth'

/**
 * `loading` — токен ещё проверяется; пока он держится, приложение не шлёт
 * запросов и рисует заглушку. Старт (`AuthProvider`) всегда начинается с
 * `loading`: access больше не хранится между перезагрузками (У9), поэтому
 * узнать `anon`/`authed` можно только запросом `refresh` по cookie. `error`
 * наружу, за пределы `AuthProvider`, не выходит — это состояние стартового
 * сетевого сбоя, а не то, с чем должны уметь работать `RequireAuth`/`RequireAnon`.
 */
export type AuthStatus = 'loading' | 'anon' | 'authed' | 'error'

/**
 * Активное учреждение: id — из claim токена, роль и название — из свежего
 * `GET /institutions` (claims могут отставать от него до 900 с). `null`,
 * пока учреждение не выбрано или членство по нему больше не активно.
 */
export type InstitutionContext = {
  id: string
  role: UserRole
  name: string
  /**
   * Название внутренней валюты учреждения (В5/б). `null`, пока не задано в
   * настройках — тогда текст берётся из `useCurrencyName()`
   * (`src/auth/useCurrencyName.ts`), а не отсюда напрямую.
   */
  currencyName: string | null
}

export type AuthValue = {
  status: AuthStatus
  user: User | null
  /** Текущий токен; нужен вызовам API от имени пользователя. */
  token: string | null
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string) => Promise<void>
  /** Выход. Локальная часть выполняется всегда, даже если сервер не ответил. */
  logout: () => Promise<void>
  /** Обновить пользователя из ответа сервера, например после смены пароля. */
  updateUser: (user: User) => void
  /** Активное учреждение, полученное из токена и списка членств. */
  institution: InstitutionContext | null
  /** Собственные членства, включая неактивные; `null` до первой загрузки. */
  memberships: Membership[] | null
  membershipsError: unknown
  /** Перечитать список членств — после создания учреждения или по «Повторить». */
  reloadMemberships: () => void
  /**
   * Сменить текущее учреждение: при необходимости переключает контекст
   * токена (`POST /institutions/{id}/token`) и запоминает выбор для
   * автовыбора при следующем входе и на F5. Если контекст токена уже
   * совпадает с `institutionId`, повторного запроса нет.
   */
  selectInstitution: (institutionId: string) => Promise<void>
}

export const AuthContext = createContext<AuthValue | null>(null)

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (value === null) {
    throw new Error('useAuth вызван вне AuthProvider')
  }
  return value
}
