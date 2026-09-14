/**
 * Главная — дашборд этапа 1 (раздел 4 плана `08-web-ux-and-deploy.md`).
 *
 * Только то, что даёт существующий API: без выбранного учреждения экран
 * смысла не имеет — сразу уводим на выбор. Дальше набор карточек зависит от
 * роли в текущем учреждении. Сетка размечена именованными областями так,
 * чтобы виджеты этапа 2 (статистика, XP и уровень, лидерборд) легли новыми
 * строками без переверстки — но сами они здесь не рисуются, пустых плашек
 * «скоро» не показываем.
 */
import { useEffect, useState } from 'react'
import { Link, Navigate } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount } from '../api/currency'
import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as marketApi from '../api/market'
import { useAuth } from '../auth/authContext'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { TRANSACTION_KIND_LABELS } from '../i18n/labels'

type Action = { to: string; label: string }

function DashboardActions({ items }: { items: Action[] }) {
  return (
    <div className="dashboard-actions">
      {items.map((item) => (
        <Link key={item.to} className="dashboard-action" to={item.to}>
          {item.label}
        </Link>
      ))}
    </div>
  )
}

function AdminDashboard({ institutionId }: { institutionId: string }) {
  const { token } = useAuth()
  const [pending, setPending] = useState<number | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (token === null) return
    let cancelled = false
    marketApi
      .listPurchases(token, institutionId, { status: 'pending' })
      .then((loaded) => {
        if (!cancelled) setPending(loaded.length)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, institutionId, attempt])

  function retry() {
    setPending(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  return (
    <div className="dashboard-grid">
      <DashboardActions
        items={[
          { to: `/institutions/${institutionId}/currency`, label: 'Начислить валюту' },
          { to: `/institutions/${institutionId}/invitations`, label: 'Пригласить ученика' },
          { to: `/institutions/${institutionId}/teachers`, label: 'Добавить преподавателя' },
          { to: `/institutions/${institutionId}/groups`, label: 'Создать группу' },
          { to: `/institutions/${institutionId}/privileges`, label: 'Добавить привилегию' },
        ]}
      />

      <div className="dashboard-primary dashboard-card">
        <p className="dashboard-card-title">ЗАЯВКИ</p>
        {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
        {loadError === null && pending === null && <ScreenState state="loading" />}
        {loadError === null && pending !== null && (
          <>
            <p>
              Заявки на выдачу: <strong>{pending}</strong>
            </p>
            <p>
              <Link to={`/institutions/${institutionId}/purchases`}>Все заявки</Link>
            </p>
          </>
        )}
      </div>
    </div>
  )
}

function TeacherDashboard({ institutionId }: { institutionId: string }) {
  const { token } = useAuth()
  const [groups, setGroups] = useState<Group[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (token === null) return
    let cancelled = false
    groupsApi
      .listGroups(token, institutionId)
      .then((loaded) => {
        if (!cancelled) setGroups(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, institutionId, attempt])

  function retry() {
    setGroups(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  return (
    <div className="dashboard-grid">
      <DashboardActions
        items={[
          { to: `/institutions/${institutionId}/currency`, label: 'Начислить валюту' },
          { to: `/institutions/${institutionId}/invitations`, label: 'Пригласить ученика' },
        ]}
      />

      <div className="dashboard-primary dashboard-card">
        <p className="dashboard-card-title">МОИ ГРУППЫ</p>
        {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
        {loadError === null && groups === null && <ScreenState state="loading" />}
        {loadError === null && groups !== null && groups.length === 0 && (
          <ScreenState
            state="empty"
            message="В ваших группах нет учеников. Состав групп задаёт администратор"
          />
        )}
        {loadError === null && groups !== null && groups.length > 0 && (
          <ul className="dashboard-transactions">
            {groups.map((group) => (
              <li key={group.id} className="dashboard-transaction">
                <Link to={`/institutions/${institutionId}/groups/${group.id}`}>{group.name}</Link>
                <span className="dashboard-transaction-meta">учеников: {group.students_count}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

function StudentDashboard({ institutionId }: { institutionId: string }) {
  const { token } = useAuth()
  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (token === null) return
    let cancelled = false
    currencyApi
      .getMyCurrency(token, institutionId)
      .then((loaded) => {
        if (!cancelled) setAccount(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, institutionId, attempt])

  function retry() {
    setAccount(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  if (loadError !== null) {
    return <ScreenState state="error" error={loadError} onRetry={retry} />
  }

  if (account === null) {
    return <ScreenState state="loading" />
  }

  // «+N сегодня» на клиенте не считаем: в ответе только последние 50 записей,
  // а не все операции за сутки — цифра была бы неверной.
  const recent = account.transactions.slice(0, 5)

  return (
    <div className="dashboard-grid">
      <div className="dashboard-primary dashboard-card dashboard-balance">
        <p className="dashboard-card-title">БАЛАНС</p>
        <Money amount={account.balance} size={24} />
        <DashboardActions
          items={[
            { to: `/institutions/${institutionId}/market`, label: 'В маркет' },
            { to: `/institutions/${institutionId}/balance`, label: 'Вся история' },
          ]}
        />
      </div>

      <div className="dashboard-list dashboard-card">
        <p className="dashboard-card-title">ОПЕРАЦИИ</p>
        {recent.length === 0 && <ScreenState state="empty" message="Операций пока нет." />}
        {recent.length > 0 && (
          <ul className="dashboard-transactions">
            {recent.map((transaction) => (
              <li key={transaction.id} className="dashboard-transaction">
                <span>{TRANSACTION_KIND_LABELS[transaction.kind]}</span>
                <Money amount={transaction.amount} showPlus />
                <span className="dashboard-transaction-meta">
                  {new Date(transaction.created_at).toLocaleString('ru-RU')}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}

export function HomePage() {
  const { institution } = useAuth()

  if (institution === null) {
    return <Navigate to="/institutions" replace />
  }

  return (
    <main className="page">
      <PageHeader title="Главная" institutionName={institution.name} />
      {institution.role === 'institution_admin' && (
        <AdminDashboard institutionId={institution.id} />
      )}
      {institution.role === 'teacher' && <TeacherDashboard institutionId={institution.id} />}
      {institution.role === 'student' && <StudentDashboard institutionId={institution.id} />}
    </main>
  )
}
