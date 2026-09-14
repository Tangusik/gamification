/**
 * Форма создания учреждения — общая для Профиля и онбординга `/institutions`.
 *
 * Что делать после успешного `POST /institutions`, решает вызывающая
 * страница через `onCreated`: Профиль просто перечитывает членства и не
 * переключает учреждение (смена — отдельной кнопкой), онбординг сразу
 * выбирает созданное учреждение текущим и уходит на дашборд.
 */
import { useState, type FormEvent } from 'react'

import type { InstitutionKind } from '../api/auth'
import * as institutionsApi from '../api/institutions'
import { useAuth } from '../auth/authContext'
import { messageForError } from '../i18n/errorMessages'
import { KIND_LABELS } from '../i18n/labels'
import { FormError } from './FormError'

const KIND_OPTIONS: InstitutionKind[] = ['school', 'camp']

type Props = {
  /** Вызывается после успешного создания с id нового учреждения. */
  onCreated: (institutionId: string) => void | Promise<void>
  submitLabel?: string
}

export function InstitutionCreateForm({ onCreated, submitLabel = 'Создать учреждение' }: Props) {
  const { token } = useAuth()

  const [name, setName] = useState('')
  const [kind, setKind] = useState<InstitutionKind>('school')
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null) return
    setCreating(true)
    setError(null)
    try {
      const institution = await institutionsApi.createInstitution(token, name, kind)
      setName('')
      setKind('school')
      await onCreated(institution.id)
    } catch (caught) {
      setError(caught)
    } finally {
      setCreating(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <label htmlFor="institution-name">Название учреждения</label>
        <input
          id="institution-name"
          name="name"
          type="text"
          required
          maxLength={255}
          value={name}
          onChange={(event) => setName(event.target.value)}
          disabled={creating}
        />
      </div>

      <div className="field">
        <label htmlFor="institution-kind">Тип</label>
        <select
          id="institution-kind"
          name="kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as InstitutionKind)}
          disabled={creating}
        >
          {KIND_OPTIONS.map((option) => (
            <option key={option} value={option}>
              {KIND_LABELS[option]}
            </option>
          ))}
        </select>
      </div>

      <FormError message={error === null ? undefined : messageForError(error)} />

      <button type="submit" disabled={creating}>
        {creating ? 'Создаём…' : submitLabel}
      </button>
    </form>
  )
}
