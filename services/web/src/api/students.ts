/**
 * Ученики учреждения — доступно только `institution_admin`.
 *
 * Форма члена (`InstitutionMember`) общая с `teachers.ts`.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`. Исключение —
 * `listStudents`: у него необязательный query-параметр `group_id`, который
 * добавляется уже после пути без слэша.
 */
import type { InstitutionMember, UpdateMemberInput } from './teachers'
import { request } from './client'

export type { InstitutionMember, UpdateMemberInput }

/**
 * Ученик со своим балансом валюты. Отдельный тип поверх `InstitutionMember`,
 * а не поле в общем типе: у преподавателей (`teachers.ts`) баланса нет, и
 * добавлять его в общую форму значило бы соврать про ответ `GET /teachers`.
 */
export type StudentMember = InstitutionMember & { balance: number }

function studentsPath(institutionId: string): string {
  return `/institutions/${encodeURIComponent(institutionId)}/students`
}

export function listStudents(
  token: string,
  institutionId: string,
  groupId?: string,
): Promise<StudentMember[]> {
  const query = groupId !== undefined ? `?group_id=${encodeURIComponent(groupId)}` : ''
  return request<StudentMember[]>(`${studentsPath(institutionId)}${query}`, { token })
}

export function updateStudent(
  token: string,
  institutionId: string,
  userId: string,
  input: UpdateMemberInput,
): Promise<InstitutionMember> {
  return request<InstitutionMember>(`${studentsPath(institutionId)}/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    json: input,
    token,
  })
}
