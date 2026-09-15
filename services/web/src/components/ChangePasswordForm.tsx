/**
 * Форма смены пароля — общая для `/password` (принудительная смена
 * временного пароля) и Профиля (смена пароля по желанию).
 *
 * Что делать после успеха, решает вызывающая страница через `onSuccess`:
 * `/password` уходит на дашборд, Профиль остаётся на месте и показывает
 * `SavedNotice`.
 */
import { useState, type FormEvent } from 'react'

import * as authApi from '../api/auth'
import type { User } from '../api/auth'
import { useAuth } from '../auth/authContext'
import { messageForError } from '../i18n/errorMessages'
import { FieldError } from './FieldError'
import { FormError } from './FormError'

const MISMATCH_MESSAGE = 'Пароли не совпадают.'

type Props = {
  onSuccess: (user: User) => void
  submitLabel?: string
}

export function ChangePasswordForm({ onSuccess, submitLabel = 'Сохранить пароль' }: Props) {
  const { token, user, login, logout } = useAuth()

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [mismatch, setMismatch] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || user === null) return
    if (password !== confirm) {
      setMismatch(true)
      setError(null)
      return
    }
    setMismatch(false)
    setPending(true)
    setError(null)
    try {
      const updated = await authApi.changePassword(token, password)
      // Смена пароля гасит все сессии пользователя, включая текущую (вопрос 5
      // плана `10-refresh.md`) — прежний access и refresh-cookie уже
      // недействительны. Входим заново тем же email и только что отправленным
      // паролем, а не `updateUser(updated)`: без нового `login` следующий
      // запрос получил бы 401 и разлогинил пользователя, который только что
      // ввёл новый пароль.
      try {
        await login(user.email, password)
      } catch (loginFailed) {
        // Пароль сменился на сервере, но новая сессия не поднялась. Оставлять
        // пользователя с погашенной сессией нельзя — локальный выход;
        // `RequireAuth` сам уведёт на `/login` по смене статуса на `anon`.
        await logout()
        setError(loginFailed)
        return
      }
      setPassword('')
      setConfirm('')
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
        <label htmlFor="new-password">Новый пароль</label>
        <input
          id="new-password"
          name="password"
          type="password"
          autoComplete="new-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={pending}
        />
      </div>

      <div className="field">
        <label htmlFor="new-password-confirm">Повтор пароля</label>
        <input
          id="new-password-confirm"
          name="password_confirm"
          type="password"
          autoComplete="new-password"
          required
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          disabled={pending}
          aria-invalid={mismatch}
        />
        <FieldError message={mismatch ? MISMATCH_MESSAGE : undefined} />
      </div>

      <FormError message={error === null ? undefined : messageForError(error)} />

      <button type="submit" disabled={pending}>
        {pending ? 'Сохраняем…' : submitLabel}
      </button>
    </form>
  )
}
