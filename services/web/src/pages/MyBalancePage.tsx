/**
 * Баланс и история операций текущего пользователя — `/institutions/:id/balance`.
 *
 * Доступно только `student`: эндпоинт `GET /me/currency` рассчитан на эту
 * роль, для остальных сервер ответит `INSUFFICIENT_ROLE` — `ScreenState`
 * показывает для этого кода отдельный экран «Нет доступа».
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount, CurrencyTransaction } from '../api/currency'
import { useAuth } from '../auth/authContext'
import { useCurrencyName } from '../auth/useCurrencyName'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { ROLE_LABELS, TRANSACTION_KIND_LABELS } from '../i18n/labels'

function authorLabel(transaction: CurrencyTransaction): string {
  return transaction.created_by_name ?? ROLE_LABELS[transaction.created_by_role]
}

export function MyBalancePage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const currencyName = useCurrencyName()

  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    currencyApi
      .getMyCurrency(token, id)
      .then((loaded) => {
        if (!cancelled) setAccount(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, attempt])

  function retry() {
    setAccount(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  return (
    <main className="page">
      <PageHeader title="История операций" institutionName={institution?.name} />

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}

      {loadError === null && account === null && <ScreenState state="loading" />}

      {loadError === null && account !== null && (
        <>
          <p className="market-balance">
            Баланс: <Money amount={account.balance} size={20} /> {currencyName}
          </p>

          {account.transactions.length === 0 && (
            <ScreenState state="empty" message="Операций пока нет" />
          )}

          {account.transactions.length > 0 && (
            <ul className="institution-list">
              {account.transactions.map((transaction) => (
                <li key={transaction.id} className="institution-item">
                  <div>
                    <p className="institution-name">
                      {TRANSACTION_KIND_LABELS[transaction.kind]}
                    </p>
                    <p className="institution-meta">
                      {authorLabel(transaction)} ·{' '}
                      {new Date(transaction.created_at).toLocaleString('ru-RU')}
                      {transaction.comment !== null && ` · ${transaction.comment}`}
                    </p>
                  </div>
                  <Money amount={transaction.amount} showPlus />
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  )
}
