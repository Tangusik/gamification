/**
 * Смена временного пароля — `/password`.
 *
 * Пока у пользователя стоит `must_change_password`, `RequireAuth` уводит сюда
 * с любого другого защищённого маршрута. Сама форма — общий компонент
 * `ChangePasswordForm` (используется и в Профиле); после успеха уходим на
 * `/`. Смена пароля гасит все сессии (вопрос 5 плана `10-refresh.md`), форма
 * сама входит заново новым паролем — обновлённый `user` (флаг уже `false`)
 * приходит с этим новым входом, иначе редирект сработал бы снова.
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
