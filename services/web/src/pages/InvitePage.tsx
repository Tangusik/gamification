/**
 * Принятие приглашения по ссылке `/invite#<token>`.
 *
 * Токен лежит во фрагменте (`location.hash`), а не в пути или query, — он
 * не должен уходить на сервер (см. `../../.claude/knowledge/gamification-service/03-invitations.md`).
 * Клиент читает его сам и отправляет в теле POST.
 *
 * Защита от двойной отправки в React StrictMode — через `useRef`: эффект
 * выполняется дважды на монтировании, а повторный запрос не нужен, хотя
 * принятие и идемпотентно.
 *
 * После успеха — кнопка «Перейти в учреждение»: выбирает принятое членство
 * текущим (`selectInstitution`) и уводит на `/`.
 *
 * Кроме кнопки, после успешного accept список членств перечитывается сам
 * (`reloadMemberships`) — иначе принятое приглашение не появится ни в
 * «Мои учреждения» на `/profile`, ни в автовыборе `AuthProvider`. Если на
 * момент accept текущего учреждения ещё не было (новый пользователь, только
 * что зарегистрировавшийся), принятое членство выбирается текущим само —
 * то же правило автовыбора «единственное активное» (В3), просто вызванное
 * сразу, а не на следующей перезагрузке. Если текущее учреждение уже есть
 * (у пользователя было ранее выбранное), оно не трогается — пользователь сам
 * решает через кнопку ниже.
 */
import { useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router'

import type { Membership } from '../api/auth'
import * as institutionsApi from '../api/institutions'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { messageForError } from '../i18n/errorMessages'
import { ROLE_LABELS } from '../i18n/labels'

type Phase =
  | { kind: 'checking' }
  | { kind: 'empty' }
  | { kind: 'error'; error: unknown }
  | { kind: 'done'; membership: Membership }

export function InvitePage() {
  const { token, institution, selectInstitution, reloadMemberships } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const started = useRef(false)
  // Отдельный флаг от `started`: тот закрывает сам запрос accept (эффект
  // ниже реагирует на уже готовый результат и StrictMode проигрывает его
  // дважды тем же порядком).
  const settled = useRef(false)

  const inviteToken = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash

  const [phase, setPhase] = useState<Phase>(
    inviteToken.length === 0 ? { kind: 'empty' } : { kind: 'checking' },
  )
  const [going, setGoing] = useState(false)
  const [goError, setGoError] = useState<unknown>(null)

  useEffect(() => {
    if (started.current) return
    if (inviteToken.length === 0) return
    if (token === null) return
    started.current = true

    institutionsApi
      .acceptInvitation(token, inviteToken)
      .then((membership) => setPhase({ kind: 'done', membership }))
      .catch((error: unknown) => setPhase({ kind: 'error', error }))
  }, [token, inviteToken])

  useEffect(() => {
    if (phase.kind !== 'done' || settled.current) return
    settled.current = true

    reloadMemberships()
    if (institution === null) {
      // Своего учреждения ещё не было — становимся участником принятого
      // сразу, без ожидания следующего автовыбора `AuthProvider`.
      void selectInstitution(phase.membership.institution_id).catch(() => {
        // Необязательная попытка: не получилось — пользователь всё равно
        // может нажать «Перейти в учреждение» ниже.
      })
    }
  }, [phase, institution, reloadMemberships, selectInstitution])

  async function handleGo(institutionId: string) {
    setGoing(true)
    setGoError(null)
    try {
      await selectInstitution(institutionId)
      navigate('/', { replace: true })
    } catch (caught) {
      setGoError(caught)
    } finally {
      setGoing(false)
    }
  }

  return (
    <main className="page page-narrow">
      <PageHeader title="Приглашение" />

      {phase.kind === 'checking' && (
        <p className="page-status" role="status">
          Принимаем приглашение…
        </p>
      )}

      {phase.kind === 'empty' && (
        <FormError message="Ссылка приглашения не содержит кода. Проверьте адрес." />
      )}

      {phase.kind === 'error' && <FormError message={messageForError(phase.error)} />}

      {phase.kind === 'done' && (
        <>
          <p>
            Готово: вы участник учреждения «{phase.membership.name}» в роли{' '}
            {ROLE_LABELS[phase.membership.role]}.
          </p>
          <button
            type="button"
            onClick={() => void handleGo(phase.membership.institution_id)}
            disabled={going}
          >
            {going ? 'Переходим…' : 'Перейти в учреждение'}
          </button>
          {goError !== null && <FormError message={messageForError(goError)} />}
        </>
      )}
    </main>
  )
}
