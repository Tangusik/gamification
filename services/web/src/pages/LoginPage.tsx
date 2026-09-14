/** Страница входа. */
import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'

import { ApiError } from '../api/errors'
import { useAuth } from '../auth/authContext'
import { targetFromState } from '../auth/fromLocation'
import { FieldError } from '../components/FieldError'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setError(null)
    try {
      await login(email, password)
      navigate(targetFromState(location.state), { replace: true })
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setPending(false)
    }
  }

  const fieldErrors = error?.fieldErrors

  return (
    <main className="page page-narrow">
      <h1>Вход</h1>
      <form className="form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="login-email">Почта</label>
          <input
            id="login-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={pending}
            aria-invalid={fieldErrors?.email !== undefined}
          />
          <FieldError message={fieldErrors?.email} />
        </div>

        <div className="field">
          <label htmlFor="login-password">Пароль</label>
          <input
            id="login-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={pending}
            aria-invalid={fieldErrors?.password !== undefined}
          />
          <FieldError message={fieldErrors?.password} />
        </div>

        <FormError message={error === null ? undefined : messageForError(error)} />

        <button type="submit" disabled={pending}>
          {pending ? 'Входим…' : 'Войти'}
        </button>
      </form>

      <p>
        Нет учётной записи?{' '}
        <Link to="/register" state={location.state}>
          Зарегистрироваться
        </Link>
      </p>
    </main>
  )
}
