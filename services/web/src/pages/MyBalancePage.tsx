/**
 * Баланс и история операций текущего пользователя — `/institutions/:id/balance`.
 *
 * Доступно только `student`: эндпоинт `GET /me/currency` рассчитан на эту
 * роль, для остальных сервер ответит `INSUFFICIENT_ROLE`.
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount, CurrencyTransaction } from '../api/currency'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { ROLE_LABELS, TRANSACTION_KIND_LABELS } from '../i18n/labels'

function authorLabel(transaction: CurrencyTransaction): string {
  return transaction.created_by_name ?? ROLE_LABELS[transaction.created_by_role]
}

function formatAmount(amount: number): string {
  return amount > 0 ? `+${amount}` : `${amount}`
}

export function MyBalancePage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

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
    <>
      <main className="page">
        <h1>Баланс</h1>

        {loadError !== null && (
          <>
            <FormError message={messageForError(loadError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {loadError === null && account === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {account !== null && (
          <>
            <p>
              Баланс: <strong>{account.balance}</strong>
            </p>

            {account.transactions.length === 0 && <p>Операций пока нет.</p>}

            {account.transactions.length > 0 && (
              <ul className="institution-list">
                {account.transactions.map((transaction) => (
                  <li key={transaction.id} className="institution-item">
                    <div>
                      <p className="institution-name">
                        {TRANSACTION_KIND_LABELS[transaction.kind]}: {formatAmount(transaction.amount)}
                      </p>
                      <p className="institution-meta">
                        {authorLabel(transaction)} ·{' '}
                        {new Date(transaction.created_at).toLocaleString()}
                        {transaction.comment !== null && ` · ${transaction.comment}`}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </main>
    </>
  )
}
