/**
 * Форма смены имени в профиле — раздел «Имя» на `/profile`.
 *
 * `full_name` допускает `null` (сброс имени) — пустое поле при сохранении
 * отправляется именно как `null`, а не как пустая строка.
 */
import { useState, type FormEvent } from 'react'

import * as authApi from '../api/auth'
import type { User } from '../api/auth'
import { useAuth } from '../auth/authContext'
import { messageForError } from '../i18n/errorMessages'
import { FormError } from './FormError'

const MAX_LENGTH = 100

type Props = {
  onSuccess: (user: User) => void
  submitLabel?: string
}

export function ChangeNameForm({ onSuccess, submitLabel = 'Сохранить имя' }: Props) {
  const { token, user, updateUser } = useAuth()

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null) return
    setPending(true)
    setError(null)
    try {
      const trimmed = fullName.trim()
      const updated = await authApi.updateFullName(token, trimmed === '' ? null : trimmed)
      updateUser(updated)
      onSuccess(updated)
    } catch (caught) {
      setError(caught)
    } finally {
      setPending(false)
    }
  }

  return (
    <form className="form" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <label htmlFor="full-name">Имя</label>
        <input
          id="full-name"
          name="full_name"
          type="text"
          maxLength={MAX_LENGTH}
          value={fullName}
          onChange={(event) => setFullName(event.target.value)}
          disabled={pending}
        />
      </div>

      <FormError message={error === null ? undefined : messageForError(error)} />

      <button type="submit" disabled={pending}>
        {pending ? 'Сохраняем…' : submitLabel}
      </button>
    </form>
  )
}
