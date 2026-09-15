/**
 * Настройки учреждения — `/institutions/:id/settings`: переименование и
 * название валюты (В5/б); тип (`kind`) только показывается (S1).
 *
 * После успеха — `SavedNotice` на месте (без ухода со страницы) и
 * `reloadMemberships()`: без него новое название не появилось бы в
 * контексте учреждения (`useAuth().institution`) и в меню до следующего
 * входа.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import { ApiError } from '../api/errors'
import * as institutionsApi from '../api/institutions'
import type { Institution } from '../api/institutions'
import { useAuth } from '../auth/authContext'
import { FieldError } from '../components/FieldError'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { SavedNotice } from '../components/SavedNotice'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { KIND_LABELS } from '../i18n/labels'

export function InstitutionSettingsPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution, reloadMemberships } = useAuth()

  const [loaded, setLoaded] = useState<Institution | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [name, setName] = useState('')
  const [currencyName, setCurrencyName] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<ApiError | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    institutionsApi
      .getInstitution(token, id)
      .then((data) => {
        if (!cancelled) {
          setLoaded(data)
          setName(data.name)
          setCurrencyName(data.currency_name ?? '')
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
    setLoaded(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined || loaded === null) return

    const trimmedCurrencyName = currencyName.trim()
    const patch: { name: string; currency_name?: string | null } = { name }
    const nextCurrencyName = trimmedCurrencyName === '' ? null : trimmedCurrencyName
    if (nextCurrencyName !== loaded.currency_name) {
      patch.currency_name = nextCurrencyName
    }

    setSaving(true)
    setSaveError(null)
    setSaved(false)
    try {
      const updated = await institutionsApi.updateInstitution(token, id, patch)
      setLoaded(updated)
      setName(updated.name)
      setCurrencyName(updated.currency_name ?? '')
      setSaved(true)
      reloadMemberships()
    } catch (caught) {
      setSaveError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setSaving(false)
    }
  }

  const fieldErrors = saveError?.fieldErrors

  return (
    <main className="page">
      <PageHeader title="Настройки учреждения" institutionName={institution?.name} />

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}

      {loadError === null && loaded === null && <ScreenState state="loading" />}

      {loaded !== null && (
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
              onChange={(event) => {
                setName(event.target.value)
                setSaved(false)
              }}
              disabled={saving}
              aria-invalid={fieldErrors?.name !== undefined}
            />
            <FieldError message={fieldErrors?.name} />
          </div>

          <div className="field">
            <label htmlFor="institution-settings-currency-name">
              Название валюты (пусто — по умолчанию)
            </label>
            <input
              id="institution-settings-currency-name"
              name="currency_name"
              type="text"
              maxLength={32}
              value={currencyName}
              onChange={(event) => {
                setCurrencyName(event.target.value)
                setSaved(false)
              }}
              disabled={saving}
              aria-invalid={fieldErrors?.currency_name !== undefined}
            />
            <FieldError message={fieldErrors?.currency_name} />
          </div>

          <div className="field">
            <label htmlFor="institution-settings-kind">Тип</label>
            <input
              id="institution-settings-kind"
              type="text"
              value={KIND_LABELS[loaded.kind]}
              disabled
              readOnly
            />
          </div>

          <FormError message={saveError === null ? undefined : messageForError(saveError)} />

          <button type="submit" disabled={saving}>
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </button>
          <SavedNotice show={saved} />
        </form>
      )}
    </main>
  )
}
