/**
 * Защита маршрутов для авторизованных.
 *
 * Проверка живёт в роутере, а не внутри страниц: nginx отдаёт `index.html` на
 * любой адрес, поэтому единственное место, где решается доступ, — маршрут.
 */
import { Navigate, Outlet, useLocation } from 'react-router'

import { useAuth } from './authContext'
import { AuthPending } from './AuthPending'

/** Путь, с которого редирект на смену пароля не делается — иначе цикл. */
const CHANGE_PASSWORD_PATH = '/password'

export function RequireAuth() {
  const { status, user } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    return <AuthPending />
  }
  if (status === 'anon') {
    // Цель сохраняем, чтобы после входа вернуть пользователя куда он шёл.
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  if (user?.must_change_password === true && location.pathname !== CHANGE_PASSWORD_PATH) {
    // Временный пароль ещё не сменён: любой защищённый маршрут, кроме самой
    // страницы смены пароля, уводит туда. Условие на pathname и есть то, что
    // не даёт циклу замкнуться — сама `/password` под этой же проверкой.
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />
  }
  return <Outlet />
}
