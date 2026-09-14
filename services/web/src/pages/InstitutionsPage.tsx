/**
 * Онбординг и выбор учреждения — `/institutions`.
 *
 * Если учреждение уже выбрано (автовыбор по единственному или последнему
 * активному членству ведёт `AuthProvider`), сюда попадать незачем — сразу
 * уходим на `/`. Иначе два случая: активных членств нет — текст и та же
 * форма создания учреждения, что и в Профиле, после создания учреждение
 * сразу становится текущим и происходит переход на `/` (иначе пользователь
 * застрянет на онбординге); активных несколько без выбора — список с явной
 * кнопкой «Выбрать».
 *
 * Семь прежних кнопок действий (Управление, Приглашения, Баланс, Начисления,
 * Маркет, Покупки, Выбрать) отсюда убраны — их заменяет меню (A2) и Профиль.
 * Смена учреждения при уже выбранном контексте — только в Профиле.
 */
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router'

import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { InstitutionCreateForm } from '../components/InstitutionCreateForm'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { KIND_LABELS, ROLE_LABELS } from '../i18n/labels'

export function InstitutionsPage() {
  const { institution, memberships, membershipsError, reloadMemberships, selectInstitution } = useAuth()
  const navigate = useNavigate()

  const [selectingId, setSelectingId] = useState<string | null>(null)
  const [selectError, setSelectError] = useState<unknown>(null)

  const active = memberships?.filter((membership) => membership.status === 'active') ?? null

  async function goTo(institutionId: string) {
    setSelectingId(institutionId)
    setSelectError(null)
    try {
      await selectInstitution(institutionId)
      navigate('/', { replace: true })
    } catch (caught) {
      setSelectError(caught)
    } finally {
      setSelectingId(null)
    }
  }

  if (institution !== null) {
    return <Navigate to="/" replace />
  }

  return (
    <main className="page">
      <PageHeader title="Учреждения" />

      {membershipsError !== null && (
        <ScreenState state="error" error={membershipsError} onRetry={reloadMemberships} />
      )}

      {membershipsError === null && active === null && <ScreenState state="loading" />}

      {membershipsError === null && active !== null && active.length === 0 && (
        <>
          <ScreenState
            state="empty"
            message="Создайте учреждение или откройте ссылку-приглашение от школы."
          />
          <InstitutionCreateForm onCreated={(id) => goTo(id)} />
        </>
      )}

      {membershipsError === null && active !== null && active.length > 0 && (
        <ul className="institution-list">
          {active.map((membership) => {
            const busy = selectingId === membership.institution_id
            return (
              <li key={membership.institution_id} className="institution-item">
                <div>
                  <p className="institution-name">{membership.name}</p>
                  <p className="institution-meta">
                    {KIND_LABELS[membership.kind]} · {ROLE_LABELS[membership.role]}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void goTo(membership.institution_id)}
                  disabled={busy || selectingId !== null}
                >
                  {busy ? 'Выбираем…' : 'Выбрать'}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      {selectError !== null && <FormError message={messageForError(selectError)} />}
    </main>
  )
}
