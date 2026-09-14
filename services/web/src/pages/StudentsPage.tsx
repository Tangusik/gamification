/**
 * Ученики учреждения — `/institutions/:id/students`: фильтр по группе, имя,
 * группы ученика (добавить/убрать), статус, ссылка на приглашения.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as studentsApi from '../api/students'
import type { InstitutionMember } from '../api/students'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { STATUS_LABELS } from '../i18n/labels'

const STATUS_OPTIONS: InstitutionMember['status'][] = ['active', 'suspended']

export function StudentsPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

  const [groups, setGroups] = useState<Group[] | null>(null)
  const [groupFilter, setGroupFilter] = useState('')

  const [items, setItems] = useState<InstitutionMember[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [busyId, setBusyId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)
  const [addGroupDrafts, setAddGroupDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    if (token === null || id === undefined) return
    groupsApi
      .listGroups(token, id)
      .then(setGroups)
      .catch(() => undefined)
  }, [token, id])

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    studentsApi
      .listStudents(token, id, groupFilter === '' ? undefined : groupFilter)
      .then((loaded) => {
        if (!cancelled) setItems(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, groupFilter, attempt])

  function retry() {
    setItems(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  function groupName(groupId: string): string {
    return groups?.find((group) => group.id === groupId)?.name ?? groupId
  }

  async function handleStatusChange(member: InstitutionMember, status: InstitutionMember['status']) {
    if (token === null || id === undefined) return
    setBusyId(member.user_id)
    setActionError(null)
    try {
      await studentsApi.updateStudent(token, id, member.user_id, { status })
      retry()
    } catch (caught) {
      setActionError(caught)
    } finally {
      setBusyId(null)
    }
  }

  async function handleAddToGroup(member: InstitutionMember) {
    if (token === null || id === undefined) return
    const targetGroupId = addGroupDrafts[member.user_id]
    if (targetGroupId === undefined || targetGroupId === '') return
    setBusyId(member.user_id)
    setActionError(null)
    try {
      await groupsApi.addStudentToGroup(token, id, targetGroupId, member.user_id)
      setAddGroupDrafts((prev) => ({ ...prev, [member.user_id]: '' }))
      retry()
    } catch (caught) {
      setActionError(caught)
    } finally {
      setBusyId(null)
    }
  }

  async function handleRemoveFromGroup(member: InstitutionMember, targetGroupId: string) {
    if (token === null || id === undefined) return
    setBusyId(member.user_id)
    setActionError(null)
    try {
      await groupsApi.removeStudentFromGroup(token, id, targetGroupId, member.user_id)
      retry()
    } catch (caught) {
      setActionError(caught)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <>
      <main className="page">
        <h1>Ученики</h1>

        <p>
          <Link to={`/institutions/${id}/invitations`}>Приглашения</Link>
        </p>

        <div className="field">
          <label htmlFor="student-group-filter">Группа</label>
          <select
            id="student-group-filter"
            value={groupFilter}
            onChange={(event) => setGroupFilter(event.target.value)}
          >
            <option value="">Все</option>
            {(groups ?? []).map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </div>

        {loadError !== null && (
          <>
            <FormError message={messageForError(loadError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {loadError === null && items === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {items !== null && items.length === 0 && <p>Учеников пока нет.</p>}

        {items !== null && items.length > 0 && (
          <ul className="institution-list">
            {items.map((member) => {
              const busy = busyId === member.user_id
              const memberGroups = member.group_ids
              const addableGroups = (groups ?? []).filter(
                (group) => !memberGroups.includes(group.id),
              )
              return (
                <li key={member.user_id} className="institution-item">
                  <div>
                    <p className="institution-name">{member.display_name ?? member.user_id}</p>
                    <p className="institution-meta">
                      {memberGroups.length === 0
                        ? 'без группы'
                        : memberGroups.map((groupId) => groupName(groupId)).join(', ')}
                    </p>
                    {memberGroups.map((groupId) => (
                      <button
                        key={groupId}
                        type="button"
                        onClick={() => void handleRemoveFromGroup(member, groupId)}
                        disabled={busy}
                      >
                        Убрать из «{groupName(groupId)}»
                      </button>
                    ))}
                    {addableGroups.length > 0 && (
                      <>
                        <select
                          aria-label="Добавить в группу"
                          value={addGroupDrafts[member.user_id] ?? ''}
                          onChange={(event) =>
                            setAddGroupDrafts((prev) => ({
                              ...prev,
                              [member.user_id]: event.target.value,
                            }))
                          }
                          disabled={busy}
                        >
                          <option value="">Выберите группу…</option>
                          {addableGroups.map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.name}
                            </option>
                          ))}
                        </select>
                        <button
                          type="button"
                          onClick={() => void handleAddToGroup(member)}
                          disabled={busy || (addGroupDrafts[member.user_id] ?? '') === ''}
                        >
                          Добавить в группу
                        </button>
                      </>
                    )}
                  </div>
                  <select
                    aria-label="Статус"
                    value={member.status}
                    onChange={(event) =>
                      void handleStatusChange(member, event.target.value as InstitutionMember['status'])
                    }
                    disabled={busy}
                  >
                    {STATUS_OPTIONS.map((option) => (
                      <option key={option} value={option}>
                        {STATUS_LABELS[option]}
                      </option>
                    ))}
                  </select>
                </li>
              )
            })}
          </ul>
        )}

        {actionError !== null && <FormError message={messageForError(actionError)} />}
      </main>
    </>
  )
}
