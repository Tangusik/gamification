/**
 * Профиль пользователя — `/profile`.
 *
 * Единственное место (кроме первичного выбора на онбординге `/institutions`),
 * где можно сменить текущее учреждение — решение владельца, раздел 15 плана
 * `08-web-ux-and-deploy.md`. Каркас с меню даёт layout, поэтому здесь нет
 * `<Header />`.
 *
 * Почта — только для чтения: редактирование почты не делаем, открытый
 * вопрос В10.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router'

import { useAuth } from '../auth/authContext'
import { ChangePasswordForm } from '../components/ChangePasswordForm'
import { FormError } from '../components/FormError'
import { InstitutionCreateForm } from '../components/InstitutionCreateForm'
import { PageHeader } from '../components/PageHeader'
import { SavedNotice } from '../components/SavedNotice'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { KIND_LABELS, ROLE_LABELS, STATUS_LABELS } from '../i18n/labels'

export function ProfilePage() {
  const { user, institution, memberships, membershipsError, reloadMemberships, selectInstitution, logout } =
    useAuth()
  const navigate = useNavigate()

  const [passwordSaved, setPasswordSaved] = useState(false)
  const [switchingId, setSwitchingId] = useState<string | null>(null)
  const [switchError, setSwitchError] = useState<unknown>(null)
  const [loggingOut, setLoggingOut] = useState(false)

  async function handleSwitch(institutionId: string) {
    setSwitchingId(institutionId)
    setSwitchError(null)
    try {
      await selectInstitution(institutionId)
    } catch (caught) {
      setSwitchError(caught)
    } finally {
      setSwitchingId(null)
    }
  }

  async function handleLogout() {
    setLoggingOut(true)
    try {
      // Локальный выход безусловен, ошибку сервера здесь не ловим.
      await logout()
    } finally {
      setLoggingOut(false)
      navigate('/login', { replace: true })
    }
  }

  return (
    <main className="page">
      <PageHeader title="Профиль" institutionName={institution?.name} />

      <section className="profile-section">
        <h2>Почта</h2>
        <p>{user?.email}</p>
      </section>

      <section className="profile-section">
        <h2>Пароль</h2>
        <ChangePasswordForm onSuccess={() => setPasswordSaved(true)} />
        <SavedNotice show={passwordSaved} text="Пароль сохранён" />
      </section>

      <section className="profile-section">
        <h2>Мои учреждения</h2>

        {membershipsError !== null && (
          <ScreenState state="error" error={membershipsError} onRetry={reloadMemberships} />
        )}

        {membershipsError === null && memberships === null && <ScreenState state="loading" />}

        {membershipsError === null && memberships !== null && memberships.length === 0 && (
          <ScreenState state="empty" message="Учреждений пока нет." />
        )}

        {membershipsError === null && memberships !== null && memberships.length > 0 && (
          <ul className="institution-list">
            {memberships.map((membership) => {
              const isCurrent = membership.institution_id === institution?.id
              const canSwitch = membership.status === 'active' && !isCurrent
              const busy = switchingId === membership.institution_id
              return (
                <li key={membership.institution_id} className="institution-item">
                  <div>
                    <p className="institution-name">
                      {membership.name}
                      {isCurrent && ' · текущее'}
                    </p>
                    <p className="institution-meta">
                      {KIND_LABELS[membership.kind]} · {ROLE_LABELS[membership.role]} ·{' '}
                      {STATUS_LABELS[membership.status]}
                    </p>
                  </div>
                  {canSwitch && (
                    <button
                      type="button"
                      onClick={() => void handleSwitch(membership.institution_id)}
                      disabled={busy || switchingId !== null}
                    >
                      {busy ? 'Переключаем…' : 'Сделать текущим'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {switchError !== null && <FormError message={messageForError(switchError)} />}
      </section>

      <section className="profile-section">
        <h2>Новое учреждение</h2>
        {/*
         * Новое учреждение текущим автоматически не становится — смена
         * происходит отдельной кнопкой «Сделать текущим» выше.
         */}
        <InstitutionCreateForm onCreated={() => reloadMemberships()} />
      </section>

      <section className="profile-section">
        <button type="button" onClick={() => void handleLogout()} disabled={loggingOut}>
          {loggingOut ? 'Выходим…' : 'Выход'}
        </button>
      </section>
    </main>
  )
}
