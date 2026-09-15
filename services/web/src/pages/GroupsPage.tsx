/**
 * Группы учреждения — `/institutions/:id/groups`: список и создание.
 *
 * `institution_admin` — создание и переход в карточку группы. `teacher`
 * получает тот же `GET /groups` (`require_admin_or_teacher` на бэкенде,
 * `../../gamification-service/07-currency.md`), но видит только список, без
 * формы создания — карточка группы для него тоже read-only (`GroupPage`).
 */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'

export function GroupsPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const isAdmin = institution?.role === 'institution_admin'

  const [items, setItems] = useState<Group[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [name, setName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    groupsApi
      .listGroups(token, id)
      .then((loaded) => {
        if (!cancelled) setItems(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, attempt])

  function retry() {
    setItems(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined) return
    setCreating(true)
    setCreateError(null)
    try {
      await groupsApi.createGroup(token, id, name)
      setName('')
      retry()
    } catch (caught) {
      setCreateError(caught)
    } finally {
      setCreating(false)
    }
  }

  return (
    <main className="page">
      <PageHeader title="Группы" institutionName={institution?.name} />

      {isAdmin && (
        <form className="form" onSubmit={handleCreate} noValidate>
          <div className="field">
            <label htmlFor="group-name">Название группы</label>
            <input
              id="group-name"
              name="name"
              type="text"
              required
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={creating}
            />
          </div>

          <FormError message={createError === null ? undefined : messageForError(createError)} />

          <button type="submit" disabled={creating}>
            {creating ? 'Создаём…' : 'Создать группу'}
          </button>
        </form>
      )}

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
      {loadError === null && items === null && <ScreenState state="loading" />}
      {loadError === null && items !== null && items.length === 0 && (
        // Форма создания уже видна admin над списком — второй кнопки не нужно.
        <ScreenState state="empty" message="Групп пока нет." />
      )}

      {items !== null && items.length > 0 && (
        <ul className="institution-list">
          {items.map((group) => (
            <li key={group.id} className="institution-item">
              <div>
                <p className="institution-name">
                  <Link to={`/institutions/${id}/groups/${group.id}`}>{group.name}</Link>
                </p>
                <p className="institution-meta">
                  Преподавателей: {group.teacher_ids.length} · учеников: {group.students_count}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  )
}
