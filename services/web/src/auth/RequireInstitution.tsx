/**
 * Защита маршрутов `/institutions/:id/*`: контекст токена обязан совпадать
 * с `:id` из пути.
 *
 * Несовпадение — не молчаливый редирект, а явный экран: ссылка может вести
 * на учреждение, где у пользователя тоже есть активное членство («эта
 * ссылка относится к другому учреждению, переключиться?»), либо членства по
 * этому `:id` нет или оно не активно («нет доступа»). Реакция на 403
 * `INSTITUTION_CONTEXT_REQUIRED` в `api/client.ts` остаётся запасным путём —
 * на случай, если эта проверка что-то пропустит (например, устаревший
 * `institution_id` в claims между выпуском токена и переключением).
 */
import { useState } from 'react'
import { Outlet, useParams } from 'react-router'

import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { AuthPending } from './AuthPending'
import { useAuth } from './authContext'

export function RequireInstitution() {
  const { id } = useParams<{ id: string }>()
  const { institution, memberships, membershipsError, reloadMemberships, selectInstitution } =
    useAuth()
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState<unknown>(null)

  if (id === undefined) {
    return null
  }

  if (institution !== null && institution.id === id) {
    return <Outlet />
  }

  if (memberships === null) {
    if (membershipsError !== null) {
      return (
        <main className="page page-narrow">
          <h1>Не удалось проверить доступ</h1>
          <FormError message={messageForError(membershipsError)} />
          <button type="button" onClick={reloadMemberships}>
            Повторить
          </button>
        </main>
      )
    }
    return <AuthPending />
  }

  const membership = memberships.find((item) => item.institution_id === id)

  if (membership === undefined || membership.status !== 'active') {
    return (
      <main className="page page-narrow">
        <h1>Нет доступа к этому учреждению</h1>
        <p>Проверьте ссылку или обратитесь к администратору учреждения.</p>
      </main>
    )
  }

  const membershipId = membership.institution_id

  async function handleSwitch() {
    setSwitching(true)
    setSwitchError(null)
    try {
      await selectInstitution(membershipId)
    } catch (caught) {
      setSwitchError(caught)
    } finally {
      setSwitching(false)
    }
  }

  return (
    <main className="page page-narrow">
      <h1>Другое учреждение</h1>
      <p>
        Эта ссылка относится к учреждению «{membership.name}». Переключиться?
      </p>
      <FormError message={switchError === null ? undefined : messageForError(switchError)} />
      <button type="button" onClick={() => void handleSwitch()} disabled={switching}>
        {switching ? 'Переключаем…' : 'Переключиться'}
      </button>
    </main>
  )
}
