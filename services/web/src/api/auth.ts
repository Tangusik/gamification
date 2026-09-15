/**
 * Вызовы публичных эндпоинтов сервиса `users`.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import { request } from './client'

export type TokenResponse = {
  access_token: string
  token_type: string
}

/**
 * Заголовок CSRF-проверки cookie-пути (У6 плана `10-refresh.md`): `SameSite=Strict`
 * не спасает от собственного origin, поэтому `refresh`/`logout` дополнительно
 * требуют этот заголовок. Значение фиксировано контрактом сервера.
 */
const CSRF_HEADER = { 'X-Requested-With': 'gamification-web' }

export type User = {
  id: string
  email: string
  is_active: boolean
  is_superuser: boolean
  is_verified: boolean
  created_at: string
  /** Пока стоит — фронт уводит на `/password`, пока пароль не сменён. */
  must_change_password: boolean
}

export type InstitutionKind = 'school' | 'camp'
export type UserRole = 'student' | 'teacher' | 'institution_admin'
export type MembershipStatus = 'invited' | 'active' | 'suspended'

export type Membership = {
  institution_id: string
  name: string
  kind: InstitutionKind
  role: UserRole
  status: MembershipStatus
  /**
   * Название внутренней валюты учреждения (В5/б) — настраивается в
   * `InstitutionSettingsPage`. `null`, пока не задано; тогда используется
   * запасное слово из `useCurrencyName` (`src/auth/useCurrencyName.ts`).
   */
  currency_name: string | null
}

export function register(email: string, password: string): Promise<User> {
  return request<User>('/users/auth/register', {
    method: 'POST',
    json: { email, password },
  })
}

/**
 * Вход. Тело — form-urlencoded с полями `username` и `password`: это
 * стандартная форма OAuth2 из fastapi-users, JSON здесь не принимается.
 */
export function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>('/users/auth/jwt/login', {
    method: 'POST',
    form: { username: email, password },
    // Без заголовка сервер выдаёт access без refresh-cookie (К1 плана
    // `10-refresh.md`) — тот же контракт, что уже требуют `refresh`/`logout`.
    headers: CSRF_HEADER,
  })
}

/**
 * Обновить пару токенов по refresh-cookie (веб — только cookie-путь, У4).
 * `institution_id` — последнее выбранное учреждение (`lastInstitutionId`);
 * без него сервер сам использует то, что уже запомнено в сессии (вопрос 1
 * плана `10-refresh.md`). Cookie уходит сама — same-origin запрос её не
 * требует явно указывать.
 */
export function refresh(institutionId?: string | null): Promise<TokenResponse> {
  return request<TokenResponse>('/users/auth/jwt/refresh', {
    method: 'POST',
    json: institutionId ? { institution_id: institutionId } : {},
    headers: CSRF_HEADER,
  })
}

/**
 * Выход на сервере: гасит refresh-сессию по cookie и, если передан валидный
 * access, кладёт его `jti` в denylist (необязательно, У10). Ответ — 204 без
 * тела и всегда успешен: без `X-Requested-With` сервер ответит 403, поэтому
 * заголовок обязателен даже без access-токена.
 */
export function logout(token?: string | null): Promise<void> {
  return request<void>('/users/auth/jwt/logout', {
    method: 'POST',
    token: token ?? undefined,
    headers: CSRF_HEADER,
  })
}

export function getMe(token: string): Promise<User> {
  return request<User>('/users/me', { token })
}

/**
 * Сменить свой пароль. Ответ — обновлённый пользователь с
 * `must_change_password: false`; текущий пароль сервер не спрашивает.
 */
export function changePassword(token: string, password: string): Promise<User> {
  return request<User>('/users/me', { method: 'PATCH', json: { password }, token })
}

export function getMyInstitutions(token: string): Promise<Membership[]> {
  return request<Membership[]>('/institutions', { token })
}

/**
 * Выбрать учреждение. Ответ содержит новый токен, который **заменяет**
 * текущий: срок жизни у него — остаток жизни предъявленного.
 */
export function selectInstitution(token: string, institutionId: string): Promise<TokenResponse> {
  return request<TokenResponse>(`/institutions/${encodeURIComponent(institutionId)}/token`, {
    method: 'POST',
    token,
  })
}
