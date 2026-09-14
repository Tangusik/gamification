/**
 * Вызовы публичных эндпоинтов сервиса `gamification`, кроме членств —
 * `getMyInstitutions`/`selectInstitution` остались в `auth.ts`, чтобы не
 * трогать уже работающие сигнатуры.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import type { InstitutionKind, Membership, UserRole } from './auth'
import { request } from './client'

export type Institution = {
  id: string
  name: string
  kind: InstitutionKind
  created_at: string
}

export function getInstitution(token: string, institutionId: string): Promise<Institution> {
  return request<Institution>(`/institutions/${encodeURIComponent(institutionId)}`, { token })
}

export function updateInstitution(
  token: string,
  institutionId: string,
  name: string,
): Promise<Institution> {
  return request<Institution>(`/institutions/${encodeURIComponent(institutionId)}`, {
    method: 'PATCH',
    json: { name },
    token,
  })
}

export function createInstitution(
  token: string,
  name: string,
  kind: InstitutionKind,
): Promise<{ id: string }> {
  return request<{ id: string }>('/institutions', {
    method: 'POST',
    json: { name, kind },
    token,
  })
}

export type InvitationRead = {
  id: string
  token: string
  role: UserRole
  max_uses: number
  uses_count: number
  created_by: string
  created_at: string
  revoked_at: string | null
}

export function createInvitation(
  token: string,
  institutionId: string,
  maxUses: number,
): Promise<InvitationRead> {
  return request<InvitationRead>(
    `/institutions/${encodeURIComponent(institutionId)}/invitations`,
    { method: 'POST', json: { max_uses: maxUses }, token },
  )
}

export function listInvitations(token: string, institutionId: string): Promise<InvitationRead[]> {
  return request<InvitationRead[]>(
    `/institutions/${encodeURIComponent(institutionId)}/invitations`,
    { token },
  )
}

export function revokeInvitation(
  token: string,
  institutionId: string,
  invitationId: string,
): Promise<void> {
  return request<void>(
    `/institutions/${encodeURIComponent(institutionId)}/invitations/${encodeURIComponent(invitationId)}`,
    { method: 'DELETE', token },
  )
}

/**
 * Принять приглашение по токену из фрагмента ссылки (`/invite#<token>`).
 * Контекст учреждения не нужен — эндпоинт сам находит его по приглашению.
 */
export function acceptInvitation(token: string, invitationToken: string): Promise<Membership> {
  return request<Membership>('/institutions/invitations/accept', {
    method: 'POST',
    json: { token: invitationToken },
    token,
  })
}
