/**
 * Преподаватели учреждения — `/institutions/:id/teachers`: создание, список,
 * правка имени и статуса.
 *
 * Требует, чтобы контекст токена совпадал с `:id` — как и остальные разделы
 * администрирования, вход в них с `InstitutionsPage` уже переключает контекст.
 *
 * UUID на экран не выводится — только имя (или «Без имени») и метаданные,
 * пригодные для человека.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import * as teachersApi from '../api/teachers'
import type { InstitutionMember } from '../api/teachers'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { SavedNotice } from '../components/SavedNotice'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { STATUS_LABELS } from '../i18n/labels'

export function TeachersPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()

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
  const [savedId, setSavedId] = useState<string | null>(null)
  const [drafts, setDrafts] = useState<Record<string, string>>({})

  const [suspendTarget, setSuspendTarget] = useState<InstitutionMember | null>(null)

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
    if (nextName === '') return
    setSavingId(member.user_id)
    setSaveError(null)
    setSavedId(null)
    try {
      await teachersApi.updateTeacher(token, id, member.user_id, { display_name: nextName })
      setSavedId(member.user_id)
      retry()
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSavingId(null)
    }
  }

  async function applyStatus(member: InstitutionMember, status: InstitutionMember['status']) {
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

  function handleStatusChange(member: InstitutionMember, status: InstitutionMember['status']) {
    if (status === 'suspended') {
      setSuspendTarget(member)
      return
    }
    void applyStatus(member, status)
  }

  async function confirmSuspend() {
    if (suspendTarget === null) return
    await applyStatus(suspendTarget, 'suspended')
    setSuspendTarget(null)
  }

  return (
    <main className="page">
      <PageHeader title="Преподаватели" institutionName={institution?.name} />

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

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
      {loadError === null && items === null && <ScreenState state="loading" />}
      {loadError === null && items !== null && items.length === 0 && (
        <ScreenState state="empty" message="Преподавателей пока нет." />
      )}

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
                      placeholder="Без имени"
                      value={draftFor(member)}
                      onChange={(event) =>
                        setDrafts((prev) => ({ ...prev, [member.user_id]: event.target.value }))
                      }
                      disabled={busy}
                    />
                  </p>
                  <p className="institution-meta">
                    групп: {member.group_ids.length} · создан{' '}
                    {new Date(member.created_at).toLocaleDateString('ru-RU')}
                  </p>
                  {savedId === member.user_id && <SavedNotice show />}
                </div>
                <div>
                  <button type="button" onClick={() => void handleRename(member)} disabled={busy}>
                    Сохранить имя
                  </button>
                  <select
                    aria-label="Статус"
                    value={member.status}
                    onChange={(event) =>
                      handleStatusChange(member, event.target.value as InstitutionMember['status'])
                    }
                    disabled={busy}
                  >
                    {(['active', 'suspended'] satisfies InstitutionMember['status'][]).map((option) => (
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

      <ConfirmDialog
        open={suspendTarget !== null}
        title="Приостановить преподавателя?"
        description="Доступ пропадёт сразу."
        confirmLabel="Приостановить"
        danger
        pending={suspendTarget !== null && savingId === suspendTarget.user_id}
        onConfirm={() => void confirmSuspend()}
        onClose={() => setSuspendTarget(null)}
      />
    </main>
  )
}
