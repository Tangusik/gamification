/**
 * Преподаватели учреждения — доступно только `institution_admin`.
 *
 * Форма члена (`InstitutionMember`) общая с `students.ts`: сервер отдаёт её в
 * одном виде для обеих ролей.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import type { MembershipStatus } from './auth'
import { request } from './client'

/** Член учреждения в списках преподавателей/учеников. */
export type InstitutionMember = {
  user_id: string
  display_name: string | null
  status: MembershipStatus
  created_at: string
  group_ids: string[]
}

export type CreateTeacherInput = {
  email: string
  password: string
  display_name: string
}

export type UpdateMemberInput = {
  display_name?: string
  status?: MembershipStatus
}

function teachersPath(institutionId: string): string {
  return `/institutions/${encodeURIComponent(institutionId)}/teachers`
}

export function createTeacher(
  token: string,
  institutionId: string,
  input: CreateTeacherInput,
): Promise<InstitutionMember> {
  return request<InstitutionMember>(teachersPath(institutionId), {
    method: 'POST',
    json: input,
    token,
  })
}

export function listTeachers(token: string, institutionId: string): Promise<InstitutionMember[]> {
  return request<InstitutionMember[]>(teachersPath(institutionId), { token })
}

export function updateTeacher(
  token: string,
  institutionId: string,
  userId: string,
  input: UpdateMemberInput,
): Promise<InstitutionMember> {
  return request<InstitutionMember>(`${teachersPath(institutionId)}/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    json: input,
    token,
  })
}
