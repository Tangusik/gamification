/** Группы учреждения — `/institutions/:id/groups`: список и создание. */
import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'

import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'

export function GroupsPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

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
    <>
      <main className="page">
        <h1>Группы</h1>

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

        {items !== null && items.length === 0 && <p>Групп пока нет.</p>}

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
    </>
  )
}
