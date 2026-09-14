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
  })
}

/** Выход на сервере: гасит `jti` в denylist. Ответ — 204 без тела. */
export function logout(token: string): Promise<void> {
  return request<void>('/users/auth/jwt/logout', { method: 'POST', token })
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
