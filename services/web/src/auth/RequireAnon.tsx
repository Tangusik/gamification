/** Защита маршрутов входа и регистрации от уже авторизованного посетителя. */
import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from './authContext'
import { AuthPending } from './AuthPending'
import { targetFromState } from './fromLocation'

export function RequireAnon() {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <AuthPending />
  }
  if (status === 'authed') {
    // Единственное место перехода после входа/регистрации: страницы сами не
    // навигируют. Иначе их `navigate(цель)` гонится с этим редиректом, и
    // аноним со ссылки `/invite#<token>` уезжал на `/` вместо приглашения.
    return <Navigate to={targetFromState(location.state)} replace />
  }
  return <Outlet />
}
