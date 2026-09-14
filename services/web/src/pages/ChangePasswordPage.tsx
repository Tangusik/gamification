/**
 * Смена временного пароля — `/password`.
 *
 * Пока у пользователя стоит `must_change_password`, `RequireAuth` уводит сюда
 * с любого другого защищённого маршрута. Сама форма — общий компонент
 * `ChangePasswordForm` (используется и в Профиле); после успеха уходим на
 * `/`. Обновлённый `user` (флаг уже `false`) кладёт в контекст сама форма
 * через `updateUser`, иначе редирект сработал бы снова на следующем рендере.
 */
import { useNavigate } from 'react-router'

import { ChangePasswordForm } from '../components/ChangePasswordForm'
import { PageHeader } from '../components/PageHeader'

export function ChangePasswordPage() {
  const navigate = useNavigate()

  return (
    <main className="page page-narrow">
      <PageHeader title="Смена пароля" />
      <p>Перед началом работы установите постоянный пароль вместо временного.</p>
      <ChangePasswordForm onSuccess={() => navigate('/', { replace: true })} />
    </main>
  )
}
