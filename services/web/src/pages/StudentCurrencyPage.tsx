/**
 * Баланс, история и ручное начисление одному ученику —
 * `/institutions/:id/currency/:userId`.
 *
 * Имя ученика берётся из уже загруженного `GET /students` — отдельного
 * ресурса «один ученик» в контракте нет, тот же приём, что у `GroupPage` с
 * группой.
 *
 * `operation_id` формы начисления создаётся при монтировании и меняется
 * только после успешного ответа (201 или 200 — для формы разницы нет): при
 * сетевой ошибке или 5xx он остаётся прежним, чтобы повтор той же кнопкой
 * остался идемпотентным. У сторно свой `operation_id` на каждое нажатие —
 * повторное нажатие на уже сторнированную запись просто получит
 * `TRANSACTION_ALREADY_REVERSED`, а не создаст вторую запись.
 *
 * Роль текущего пользователя в этом учреждении сервер в токене явно не
 * отдаёт, поэтому она берётся из списка членств (`getMyInstitutions`) —
 * кнопка «Сторно» показывается только при `institution_admin`.
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import * as authApi from '../api/auth'
import type { UserRole } from '../api/auth'
import * as currencyApi from '../api/currency'
import type { CurrencyAccount, CurrencyTransaction } from '../api/currency'
import { ApiError } from '../api/errors'
import * as studentsApi from '../api/students'
import type { StudentMember } from '../api/students'
import { useAuth } from '../auth/authContext'
import { FieldError } from '../components/FieldError'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { ROLE_LABELS, TRANSACTION_KIND_LABELS } from '../i18n/labels'
import { randomOperationId } from '../utils/uuid'

function authorLabel(transaction: CurrencyTransaction): string {
  return transaction.created_by_name ?? ROLE_LABELS[transaction.created_by_role]
}

function formatAmount(amount: number): string {
  return amount > 0 ? `+${amount}` : `${amount}`
}

export function StudentCurrencyPage() {
  const { id, userId } = useParams<{ id: string; userId: string }>()
  const { token } = useAuth()

  const [students, setStudents] = useState<StudentMember[] | null>(null)
  const [role, setRole] = useState<UserRole | null>(null)

  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [amount, setAmount] = useState('')
  const [comment, setComment] = useState('')
  const [operationId, setOperationId] = useState(() => randomOperationId())
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<ApiError | null>(null)

  const [reversingId, setReversingId] = useState<string | null>(null)
  const [reverseError, setReverseError] = useState<unknown>(null)

  // Имя ученика — из общего списка, отдельного запроса на одного ученика нет.
  useEffect(() => {
    if (token === null || id === undefined) return
    studentsApi
      .listStudents(token, id)
      .then(setStudents)
      .catch(() => undefined)
  }, [token, id])

  // Роль текущего пользователя в этом учреждении — по списку своих членств.
  useEffect(() => {
    if (token === null || id === undefined) return
    authApi
      .getMyInstitutions(token)
      .then((memberships) => {
        const membership = memberships.find((item) => item.institution_id === id)
        setRole(membership?.role ?? null)
      })
      .catch(() => undefined)
  }, [token, id])

  useEffect(() => {
    if (token === null || id === undefined || userId === undefined) return
    let cancelled = false
    currencyApi
      .listStudentTransactions(token, id, userId)
      .then((loaded) => {
        if (!cancelled) setAccount(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, userId, attempt])

  function retry() {
    setAccount(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleAccrue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined || userId === undefined) return
    setSubmitting(true)
    setFormError(null)
    try {
      await currencyApi.accrue(token, id, userId, {
        operation_id: operationId,
        amount: Number(amount),
        comment: comment.trim() === '' ? null : comment,
      })
      setAmount('')
      setComment('')
      setOperationId(randomOperationId())
      retry()
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReverse(transactionId: string) {
    if (token === null || id === undefined) return
    setReversingId(transactionId)
    setReverseError(null)
    try {
      await currencyApi.reverse(token, id, transactionId, randomOperationId())
      retry()
    } catch (caught) {
      setReverseError(caught)
    } finally {
      setReversingId(null)
    }
  }

  const studentName = students?.find((member) => member.user_id === userId)?.display_name ?? userId
  const fieldErrors = formError?.fieldErrors

  const reversedIds = new Set(
    (account?.transactions ?? [])
      .filter((transaction) => transaction.kind === 'reversal' && transaction.reverses_id !== null)
      .map((transaction) => transaction.reverses_id as string),
  )

  function canReverse(transaction: CurrencyTransaction): boolean {
    return (
      role === 'institution_admin' &&
      transaction.kind === 'manual_accrual' &&
      !reversedIds.has(transaction.id)
    )
  }

  return (
    <>
      <main className="page">
        <h1>Начисление валюты — {studentName}</h1>

        <form className="form" onSubmit={handleAccrue} noValidate>
          <div className="field">
            <label htmlFor="accrual-amount">Сумма</label>
            <input
              id="accrual-amount"
              name="amount"
              type="number"
              min={1}
              max={10000}
              required
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              disabled={submitting}
              aria-invalid={fieldErrors?.amount !== undefined}
            />
            <FieldError message={fieldErrors?.amount} />
          </div>

          <div className="field">
            <label htmlFor="accrual-comment">Комментарий (необязательно)</label>
            <input
              id="accrual-comment"
              name="comment"
              type="text"
              maxLength={200}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              disabled={submitting}
              aria-invalid={fieldErrors?.comment !== undefined}
            />
            <FieldError message={fieldErrors?.comment} />
          </div>

          <FormError message={formError === null ? undefined : messageForError(formError)} />

          <button type="submit" disabled={submitting}>
            {submitting ? 'Начисляем…' : 'Начислить'}
          </button>
        </form>

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
                    {canReverse(transaction) && (
                      <button
                        type="button"
                        onClick={() => void handleReverse(transaction.id)}
                        disabled={reversingId !== null}
                      >
                        {reversingId === transaction.id ? 'Отменяем…' : 'Сторно'}
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {reverseError !== null && <FormError message={messageForError(reverseError)} />}
      </main>
    </>
  )
}
