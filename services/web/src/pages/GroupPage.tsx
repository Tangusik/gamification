/**
 * Карточка одной группы — `/institutions/:id/groups/:groupId`: переименование,
 * удаление, преподаватели и ученики группы.
 *
 * Отдельного `GET /groups/{groupId}` в контракте нет — группа берётся из
 * списка `GET /groups`.
 *
 * `teacher` получает тот же список (`require_admin_or_teacher` на бэкенде),
 * но экран здесь read-only: без формы переименования, без удаления и без
 * управления составом — те же данные, только без кнопок.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as studentsApi from '../api/students'
import type { InstitutionMember } from '../api/teachers'
import * as teachersApi from '../api/teachers'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'

function memberLabel(member: InstitutionMember): string {
  return member.display_name ?? 'Без имени'
}

export function GroupPage() {
  const { id, groupId } = useParams<{ id: string; groupId: string }>()
  const { token, institution } = useAuth()
  const navigate = useNavigate()
  const isAdmin = institution?.role === 'institution_admin'

  const [groups, setGroups] = useState<Group[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [teachers, setTeachers] = useState<InstitutionMember[] | null>(null)
  const [groupStudents, setGroupStudents] = useState<InstitutionMember[] | null>(null)
  const [allStudents, setAllStudents] = useState<InstitutionMember[] | null>(null)

  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [renameError, setRenameError] = useState<unknown>(null)

  const [deleteOpen, setDeleteOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState<unknown>(null)

  const [addTeacherId, setAddTeacherId] = useState('')
  const [addStudentId, setAddStudentId] = useState('')
  const [busyMemberId, setBusyMemberId] = useState<string | null>(null)
  const [memberActionError, setMemberActionError] = useState<unknown>(null)

  const group = groups?.find((item) => item.id === groupId) ?? null

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    groupsApi
      .listGroups(token, id)
      .then((loaded) => {
        if (!cancelled) {
          setGroups(loaded)
          const found = loaded.find((item) => item.id === groupId)
          if (found !== undefined) setName(found.name)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, groupId, attempt])

  useEffect(() => {
    if (token === null || id === undefined || groupId === undefined) return
    let cancelled = false
    teachersApi
      .listTeachers(token, id)
      .then((loaded) => {
        if (!cancelled) setTeachers(loaded)
      })
      .catch(() => undefined)
    studentsApi
      .listStudents(token, id, groupId)
      .then((loaded) => {
        if (!cancelled) setGroupStudents(loaded)
      })
      .catch(() => undefined)
    if (isAdmin) {
      studentsApi
        .listStudents(token, id)
        .then((loaded) => {
          if (!cancelled) setAllStudents(loaded)
        })
        .catch(() => undefined)
    }
    return () => {
      cancelled = true
    }
  }, [token, id, groupId, attempt, isAdmin])

  function retry() {
    setGroups(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined || groupId === undefined) return
    setRenaming(true)
    setRenameError(null)
    try {
      await groupsApi.updateGroup(token, id, groupId, name)
      retry()
    } catch (caught) {
      setRenameError(caught)
    } finally {
      setRenaming(false)
    }
  }

  async function handleDelete() {
    if (token === null || id === undefined || groupId === undefined) return
    setDeleting(true)
    setDeleteError(null)
    try {
      await groupsApi.deleteGroup(token, id, groupId)
      navigate(`/institutions/${id}/groups`, { replace: true })
    } catch (caught) {
      setDeleteError(caught)
      setDeleting(false)
      setDeleteOpen(false)
    }
  }

  async function handleAddTeacher() {
    if (token === null || id === undefined || groupId === undefined || addTeacherId === '') return
    setBusyMemberId(addTeacherId)
    setMemberActionError(null)
    try {
      await groupsApi.addTeacherToGroup(token, id, groupId, addTeacherId)
      setAddTeacherId('')
      retry()
    } catch (caught) {
      setMemberActionError(caught)
    } finally {
      setBusyMemberId(null)
    }
  }

  async function handleRemoveTeacher(userId: string) {
    if (token === null || id === undefined || groupId === undefined) return
    setBusyMemberId(userId)
    setMemberActionError(null)
    try {
      await groupsApi.removeTeacherFromGroup(token, id, groupId, userId)
      retry()
    } catch (caught) {
      setMemberActionError(caught)
    } finally {
      setBusyMemberId(null)
    }
  }

  async function handleAddStudent() {
    if (token === null || id === undefined || groupId === undefined || addStudentId === '') return
    setBusyMemberId(addStudentId)
    setMemberActionError(null)
    try {
      await groupsApi.addStudentToGroup(token, id, groupId, addStudentId)
      setAddStudentId('')
      retry()
    } catch (caught) {
      setMemberActionError(caught)
    } finally {
      setBusyMemberId(null)
    }
  }

  // Убрать из группы — без подтверждения (раздел 7, обратимо).
  async function handleRemoveStudent(userId: string) {
    if (token === null || id === undefined || groupId === undefined) return
    setBusyMemberId(userId)
    setMemberActionError(null)
    try {
      await groupsApi.removeStudentFromGroup(token, id, groupId, userId)
      retry()
    } catch (caught) {
      setMemberActionError(caught)
    } finally {
      setBusyMemberId(null)
    }
  }

  if (loadError !== null) {
    return (
      <main className="page">
        <PageHeader
          title="Группа"
          crumbs={[{ label: 'Группы', to: `/institutions/${id}/groups` }]}
          institutionName={institution?.name}
        />
        <ScreenState state="error" error={loadError} onRetry={retry} />
      </main>
    )
  }

  if (groups === null) {
    return (
      <main className="page">
        <PageHeader
          title="Группа"
          crumbs={[{ label: 'Группы', to: `/institutions/${id}/groups` }]}
          institutionName={institution?.name}
        />
        <ScreenState state="loading" />
      </main>
    )
  }

  if (group === null) {
    return (
      <main className="page">
        <PageHeader
          title="Группа"
          crumbs={[{ label: 'Группы', to: `/institutions/${id}/groups` }]}
          institutionName={institution?.name}
        />
        <p>Группа не найдена.</p>
      </main>
    )
  }

  const groupTeachers = (teachers ?? []).filter((member) => group.teacher_ids.includes(member.user_id))
  const availableTeachers = (teachers ?? []).filter(
    (member) => !group.teacher_ids.includes(member.user_id),
  )
  const availableStudents = (allStudents ?? []).filter(
    (member) => !member.group_ids.includes(groupId ?? ''),
  )

  return (
    <main className="page">
      <PageHeader
        title={group.name}
        crumbs={[{ label: 'Группы', to: `/institutions/${id}/groups` }]}
        institutionName={institution?.name}
      />

      {isAdmin && (
        <>
          <form className="form" onSubmit={handleRename} noValidate>
            <div className="field">
              <label htmlFor="group-rename">Название</label>
              <input
                id="group-rename"
                name="name"
                type="text"
                required
                maxLength={100}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={renaming}
              />
            </div>

            <FormError message={renameError === null ? undefined : messageForError(renameError)} />

            <button type="submit" disabled={renaming}>
              {renaming ? 'Сохраняем…' : 'Переименовать'}
            </button>
          </form>

          <button type="button" className="danger" onClick={() => setDeleteOpen(true)} disabled={deleting}>
            {deleting ? 'Удаляем…' : 'Удалить группу'}
          </button>
          <FormError message={deleteError === null ? undefined : messageForError(deleteError)} />
        </>
      )}

      <h2>Преподаватели</h2>
      {groupTeachers.length === 0 && <p>В группе нет преподавателей.</p>}
      {groupTeachers.length > 0 && (
        <ul className="institution-list">
          {groupTeachers.map((member) => (
            <li key={member.user_id} className="institution-item">
              <p className="institution-name">{memberLabel(member)}</p>
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => void handleRemoveTeacher(member.user_id)}
                  disabled={busyMemberId === member.user_id}
                >
                  Убрать
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {isAdmin && teachers !== null && availableTeachers.length > 0 && (
        <div className="field">
          <label htmlFor="add-teacher">Добавить преподавателя</label>
          <select
            id="add-teacher"
            value={addTeacherId}
            onChange={(event) => setAddTeacherId(event.target.value)}
          >
            <option value="">Выберите…</option>
            {availableTeachers.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {memberLabel(member)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void handleAddTeacher()}
            disabled={addTeacherId === '' || busyMemberId !== null}
          >
            Добавить
          </button>
        </div>
      )}

      <h2>Ученики</h2>
      {groupStudents !== null && groupStudents.length === 0 && <p>В группе нет учеников.</p>}
      {groupStudents !== null && groupStudents.length > 0 && (
        <ul className="institution-list">
          {groupStudents.map((member) => (
            <li key={member.user_id} className="institution-item">
              <p className="institution-name">{memberLabel(member)}</p>
              {isAdmin && (
                <button
                  type="button"
                  onClick={() => void handleRemoveStudent(member.user_id)}
                  disabled={busyMemberId === member.user_id}
                >
                  Убрать
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      {isAdmin && allStudents !== null && availableStudents.length > 0 && (
        <div className="field">
          <label htmlFor="add-student">Добавить ученика</label>
          <select
            id="add-student"
            value={addStudentId}
            onChange={(event) => setAddStudentId(event.target.value)}
          >
            <option value="">Выберите…</option>
            {availableStudents.map((member) => (
              <option key={member.user_id} value={member.user_id}>
                {memberLabel(member)}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => void handleAddStudent()}
            disabled={addStudentId === '' || busyMemberId !== null}
          >
            Добавить
          </button>
        </div>
      )}

      {memberActionError !== null && <FormError message={messageForError(memberActionError)} />}

      <ConfirmDialog
        open={deleteOpen}
        title="Удалить группу?"
        description={
          <>
            Ученики и преподаватели не удаляются, только связь с группой. Учеников в группе:{' '}
            {groupStudents?.length ?? 0}.
          </>
        }
        confirmLabel="Удалить"
        danger
        pending={deleting}
        onConfirm={() => void handleDelete()}
        onClose={() => setDeleteOpen(false)}
      />
    </main>
  )
}
