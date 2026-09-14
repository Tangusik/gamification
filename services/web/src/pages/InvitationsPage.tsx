/**
 * Приглашения одного учреждения: список, создание, отзыв.
 *
 * Требует, чтобы контекст токена совпадал с `:id` из пути — маршрут защищён
 * `RequireInstitution`, эта страница переключение контекста не делает.
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
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'

function invitationLink(token: string): string {
  return `${window.location.origin}/invite#${token}`
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

  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [revokeError, setRevokeError] = useState<unknown>(null)

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

  async function handleRevoke(invitationId: string) {
    if (token === null || id === undefined) return
    setRevokingId(invitationId)
    setRevokeError(null)
    try {
      await institutionsApi.revokeInvitation(token, id, invitationId)
      retry()
    } catch (caught) {
      setRevokeError(caught)
    } finally {
      setRevokingId(null)
    }
  }

  return (
    <>
      <main className="page">
        <h1>Приглашения{institutionName !== undefined ? ` — ${institutionName}` : ''}</h1>

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
            {creating ? 'Создаём…' : 'Создать приглашение'}
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

        {items !== null && items.length === 0 && <p>Приглашений пока нет.</p>}

        {items !== null && items.length > 0 && (
          <ul className="institution-list">
            {items.map((invitation) => {
              const revoked = invitation.revoked_at !== null
              const busy = revokingId === invitation.id
              const link = invitationLink(invitation.token)
              return (
                <li key={invitation.id} className="institution-item">
                  <div>
                    <p className="institution-name">{revoked ? <s>{link}</s> : link}</p>
                    <p className="institution-meta">
                      Применений: {invitation.uses_count}/{invitation.max_uses} · создано{' '}
                      {new Date(invitation.created_at).toLocaleString()}
                      {revoked && ' · отозвано'}
                    </p>
                  </div>
                  {!revoked && (
                    <button
                      type="button"
                      onClick={() => void handleRevoke(invitation.id)}
                      disabled={busy || revokingId !== null}
                    >
                      {busy ? 'Отзываем…' : 'Отозвать'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {revokeError !== null && <FormError message={messageForError(revokeError)} />}
      </main>
    </>
  )
}
