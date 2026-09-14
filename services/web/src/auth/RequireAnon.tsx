/** Защита маршрутов входа и регистрации от уже авторизованного посетителя. */
import { Navigate, Outlet } from 'react-router'

import { useAuth } from './authContext'
import { AuthPending } from './AuthPending'

export function RequireAnon() {
  const { status } = useAuth()

  if (status === 'loading') {
    return <AuthPending />
  }
  if (status === 'authed') {
    return <Navigate to="/" replace />
  }
  return <Outlet />
}
