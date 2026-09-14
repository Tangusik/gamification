/**
 * Настройки учреждения — `/institutions/:id/settings`: переименование; тип
 * (`kind`) только показывается (S1).
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import * as institutionsApi from '../api/institutions'
import type { Institution } from '../api/institutions'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { KIND_LABELS } from '../i18n/labels'

export function InstitutionSettingsPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

  const [institution, setInstitution] = useState<Institution | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    institutionsApi
      .getInstitution(token, id)
      .then((loaded) => {
        if (!cancelled) {
          setInstitution(loaded)
          setName(loaded.name)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, attempt])

  function retry() {
    setInstitution(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined) return
    setSaving(true)
    setSaveError(null)
    try {
      const updated = await institutionsApi.updateInstitution(token, id, name)
      setInstitution(updated)
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <main className="page">
        <h1>Настройки учреждения</h1>

        {loadError !== null && (
          <>
            <FormError message={messageForError(loadError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {loadError === null && institution === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {institution !== null && (
          <form className="form" onSubmit={handleSubmit} noValidate>
            <div className="field">
              <label htmlFor="institution-settings-name">Название</label>
              <input
                id="institution-settings-name"
                name="name"
                type="text"
                required
                maxLength={255}
                value={name}
                onChange={(event) => setName(event.target.value)}
                disabled={saving}
              />
            </div>

            <div className="field">
              <label htmlFor="institution-settings-kind">Тип</label>
              <input
                id="institution-settings-kind"
                type="text"
                value={KIND_LABELS[institution.kind]}
                disabled
                readOnly
              />
            </div>

            <FormError message={saveError === null ? undefined : messageForError(saveError)} />

            <button type="submit" disabled={saving}>
              {saving ? 'Сохраняем…' : 'Сохранить'}
            </button>
          </form>
        )}
      </main>
    </>
  )
}
