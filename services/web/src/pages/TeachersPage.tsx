/**
 * Преподаватели учреждения — `/institutions/:id/teachers`: создание, список,
 * правка имени и статуса.
 *
 * Требует, чтобы контекст токена совпадал с `:id` — как и остальные разделы
 * администрирования, вход в них с `InstitutionsPage` уже переключает контекст.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import * as teachersApi from '../api/teachers'
import type { InstitutionMember } from '../api/teachers'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { STATUS_LABELS } from '../i18n/labels'

const STATUS_OPTIONS: InstitutionMember['status'][] = ['active', 'suspended']

export function TeachersPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

  const [items, setItems] = useState<InstitutionMember[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)

  const [savingId, setSavingId] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<unknown>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    teachersApi
      .listTeachers(token, id)
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
      await teachersApi.createTeacher(token, id, { email, password, display_name: displayName })
      setEmail('')
      setPassword('')
      setDisplayName('')
      retry()
    } catch (caught) {
      setCreateError(caught)
    } finally {
      setCreating(false)
    }
  }

  function draftFor(member: InstitutionMember): string {
    return drafts[member.user_id] ?? member.display_name ?? ''
  }

  async function handleRename(member: InstitutionMember) {
    if (token === null || id === undefined) return
    const nextName = draftFor(member).trim()
    setSavingId(member.user_id)
    setSaveError(null)
    try {
      await teachersApi.updateTeacher(token, id, member.user_id, { display_name: nextName })
      retry()
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSavingId(null)
    }
  }

  async function handleStatusChange(member: InstitutionMember, status: InstitutionMember['status']) {
    if (token === null || id === undefined) return
    setSavingId(member.user_id)
    setSaveError(null)
    try {
      await teachersApi.updateTeacher(token, id, member.user_id, { status })
      retry()
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSavingId(null)
    }
  }

  return (
    <>
      <main className="page">
        <h1>Преподаватели</h1>

        <form className="form" onSubmit={handleCreate} noValidate>
          <div className="field">
            <label htmlFor="teacher-email">Почта</label>
            <input
              id="teacher-email"
              name="email"
              type="email"
              autoComplete="off"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={creating}
            />
          </div>

          <div className="field">
            <label htmlFor="teacher-password">Временный пароль</label>
            <input
              id="teacher-password"
              name="password"
              type="text"
              autoComplete="off"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={creating}
            />
          </div>

          <div className="field">
            <label htmlFor="teacher-display-name">Имя</label>
            <input
              id="teacher-display-name"
              name="display_name"
              type="text"
              required
              maxLength={100}
              value={displayName}
              onChange={(event) => setDisplayName(event.target.value)}
              disabled={creating}
            />
          </div>

          <FormError message={createError === null ? undefined : messageForError(createError)} />

          <button type="submit" disabled={creating}>
            {creating ? 'Создаём…' : 'Добавить преподавателя'}
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

        {items !== null && items.length === 0 && <p>Преподавателей пока нет.</p>}

        {items !== null && items.length > 0 && (
          <ul className="institution-list">
            {items.map((member) => {
              const busy = savingId === member.user_id
              return (
                <li key={member.user_id} className="institution-item">
                  <div>
                    <p className="institution-name">
                      <input
                        aria-label="Имя"
                        type="text"
                        maxLength={100}
                        value={draftFor(member)}
                        onChange={(event) =>
                          setDrafts((prev) => ({ ...prev, [member.user_id]: event.target.value }))
                        }
                        disabled={busy}
                      />
                    </p>
                    <p className="institution-meta">
                      {member.user_id} · групп: {member.group_ids.length} · создан{' '}
                      {new Date(member.created_at).toLocaleDateString()}
                    </p>
                  </div>
                  <div>
                    <button type="button" onClick={() => void handleRename(member)} disabled={busy}>
                      Сохранить имя
                    </button>
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
                  </div>
                </li>
              )
            })}
          </ul>
        )}

        {saveError !== null && <FormError message={messageForError(saveError)} />}
      </main>
    </>
  )
}
