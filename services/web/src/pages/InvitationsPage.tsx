/**
 * Приглашения одного учреждения: список, создание, отзыв, копирование ссылки.
 *
 * Требует, чтобы контекст токена совпадал с `:id` из пути — маршрут защищён
 * `RequireInstitution`, эта страница переключение контекста не делает.
 *
 * `institution_admin` видит все приглашения учреждения, `teacher` — только
 * свои (`ListInvitations` на бэкенде фильтрует по автору сама, F3) — клиент
 * список не урезает.
 *
 * Название учреждения — из контекста (`useAuth().institution`), а не из
 * `location.state`: так оно не теряется на F5.
 *
 * Ссылка приглашения собирается на клиенте: `${origin}/invite#${token}` —
 * вечный контракт напечатанного QR, менять формат нельзя.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import * as institutionsApi from '../api/institutions'
import type { InvitationRead } from '../api/institutions'
import { useAuth } from '../auth/authContext'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { SavedNotice } from '../components/SavedNotice'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'

function invitationLink(token: string): string {
  return `${window.location.origin}/invite#${token}`
}

/**
 * Копирует ссылку в буфер. `navigator.clipboard` доступен только в secure
 * context — dev открыт по http (риск, знакомый по `randomOperationId`),
 * поэтому запасной путь — скрытый `textarea` и `document.execCommand('copy')`.
 */
async function copyToClipboard(text: string): Promise<boolean> {
  if (typeof navigator.clipboard?.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // падаем на запасной путь ниже
    }
  }
  const area = document.createElement('textarea')
  area.value = text
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.focus()
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(area)
  return ok
}

export function InvitationsPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const institutionName = institution?.name

  const [items, setItems] = useState<InvitationRead[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [maxUses, setMaxUses] = useState('1')
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<unknown>(null)

  const [revokeTarget, setRevokeTarget] = useState<InvitationRead | null>(null)
  const [revoking, setRevoking] = useState(false)
  const [revokeError, setRevokeError] = useState<unknown>(null)

  const [copiedId, setCopiedId] = useState<string | null>(null)
  const [copyError, setCopyError] = useState<string | null>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    institutionsApi
      .listInvitations(token, id)
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
      await institutionsApi.createInvitation(token, id, Number(maxUses))
      setMaxUses('1')
      retry()
    } catch (caught) {
      setCreateError(caught)
    } finally {
      setCreating(false)
    }
  }

  async function handleRevoke() {
    if (token === null || id === undefined || revokeTarget === null) return
    setRevoking(true)
    setRevokeError(null)
    try {
      await institutionsApi.revokeInvitation(token, id, revokeTarget.id)
      setRevokeTarget(null)
      retry()
    } catch (caught) {
      setRevokeError(caught)
    } finally {
      setRevoking(false)
    }
  }

  async function handleCopy(invitation: InvitationRead) {
    setCopyError(null)
    const ok = await copyToClipboard(invitationLink(invitation.token))
    if (ok) {
      setCopiedId(invitation.id)
      window.setTimeout(() => setCopiedId((current) => (current === invitation.id ? null : current)), 2000)
    } else {
      setCopyError('Не удалось скопировать ссылку. Скопируйте вручную.')
    }
  }

  return (
    <main className="page">
      <PageHeader title="Приглашения" institutionName={institutionName} />

      <form className="form" onSubmit={handleCreate} noValidate>
        <div className="field">
          <label htmlFor="invitation-max-uses">Число применений</label>
          <input
            id="invitation-max-uses"
            name="max_uses"
            type="number"
            min={1}
            max={100}
            required
            value={maxUses}
            onChange={(event) => setMaxUses(event.target.value)}
            disabled={creating}
          />
        </div>

        <FormError message={createError === null ? undefined : messageForError(createError)} />

        <button type="submit" disabled={creating}>
          {creating ? 'Создаём…' : 'Создать ссылку'}
        </button>
      </form>

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
      {loadError === null && items === null && <ScreenState state="loading" />}
      {loadError === null && items !== null && items.length === 0 && (
        // Форма создания уже видна выше — второй кнопки в пустом состоянии не нужно.
        <ScreenState state="empty" message="Приглашений пока нет." />
      )}

      {items !== null && items.length > 0 && (
        <ul className="institution-list">
          {items.map((invitation) => {
            const revoked = invitation.revoked_at !== null
            const link = invitationLink(invitation.token)
            return (
              <li key={invitation.id} className="institution-item">
                <div>
                  <p className="institution-name">{revoked ? <s>{link}</s> : link}</p>
                  <p className="institution-meta">
                    Применений: {invitation.uses_count}/{invitation.max_uses} · создано{' '}
                    {new Date(invitation.created_at).toLocaleString('ru-RU')}
                    {revoked && ' · отозвано'}
                  </p>
                  {copiedId === invitation.id && <SavedNotice show text="Ссылка скопирована" />}
                </div>
                {!revoked && (
                  <div>
                    <button type="button" onClick={() => void handleCopy(invitation)}>
                      Скопировать ссылку
                    </button>
                    <button type="button" className="danger" onClick={() => setRevokeTarget(invitation)}>
                      Отозвать
                    </button>
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {copyError !== null && <FormError message={copyError} />}
      {revokeError !== null && <FormError message={messageForError(revokeError)} />}

      <ConfirmDialog
        open={revokeTarget !== null}
        title="Отозвать приглашение?"
        description="Ссылка и напечатанный QR перестанут работать."
        confirmLabel="Отозвать"
        danger
        pending={revoking}
        onConfirm={() => void handleRevoke()}
        onClose={() => setRevokeTarget(null)}
      />
    </main>
  )
}
