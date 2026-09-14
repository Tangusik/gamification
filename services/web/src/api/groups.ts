/**
 * Группы учреждения — доступно только `institution_admin`.
 *
 * Отдельного `GET /groups/{groupId}` в контракте нет: карточка группы
 * находит себя в списке `listGroups`.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import { request } from './client'

export type Group = {
  id: string
  name: string
  teacher_ids: string[]
  students_count: number
}

function groupsPath(institutionId: string): string {
  return `/institutions/${encodeURIComponent(institutionId)}/groups`
}

function groupPath(institutionId: string, groupId: string): string {
  return `${groupsPath(institutionId)}/${encodeURIComponent(groupId)}`
}

export function listGroups(token: string, institutionId: string): Promise<Group[]> {
  return request<Group[]>(groupsPath(institutionId), { token })
}

export function createGroup(token: string, institutionId: string, name: string): Promise<Group> {
  return request<Group>(groupsPath(institutionId), { method: 'POST', json: { name }, token })
}

export function updateGroup(
  token: string,
  institutionId: string,
  groupId: string,
  name: string,
): Promise<Group> {
  return request<Group>(groupPath(institutionId, groupId), {
    method: 'PATCH',
    json: { name },
    token,
  })
}

export function deleteGroup(token: string, institutionId: string, groupId: string): Promise<void> {
  return request<void>(groupPath(institutionId, groupId), { method: 'DELETE', token })
}

export function addTeacherToGroup(
  token: string,
  institutionId: string,
  groupId: string,
  userId: string,
): Promise<void> {
  return request<void>(`${groupPath(institutionId, groupId)}/teachers/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    token,
  })
}

export function removeTeacherFromGroup(
  token: string,
  institutionId: string,
  groupId: string,
  userId: string,
): Promise<void> {
  return request<void>(`${groupPath(institutionId, groupId)}/teachers/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    token,
  })
}

export function addStudentToGroup(
  token: string,
  institutionId: string,
  groupId: string,
  userId: string,
): Promise<void> {
  return request<void>(`${groupPath(institutionId, groupId)}/students/${encodeURIComponent(userId)}`, {
    method: 'PUT',
    token,
  })
}

export function removeStudentFromGroup(
  token: string,
  institutionId: string,
  groupId: string,
  userId: string,
): Promise<void> {
  return request<void>(`${groupPath(institutionId, groupId)}/students/${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    token,
  })
}
