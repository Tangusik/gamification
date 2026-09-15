/**
 * Карточка одного ученика — `/institutions/:id/students/:userId`: имя, статус
 * и группы (правка — только admin), баланс с названием валюты, история,
 * форма начисления, сторно (admin) и покупки ученика.
 *
 * Имя, статус и группы ученика — из уже загруженного `GET /students`:
 * отдельного ресурса «один ученик» в контракте нет, тот же приём, что у
 * `GroupPage` с группой.
 *
 * `operation_id` формы начисления создаётся при монтировании и меняется
 * только после успешного ответа (201 или 200 — для формы разницы нет): при
 * сетевой ошибке или 5xx он остаётся прежним, чтобы повтор той же кнопкой
 * остался идемпотентным. У сторно свой `operation_id` на каждое нажатие.
 *
 * Роль текущего пользователя — из контекста учреждения (`useAuth`), отдельный
 * запрос `getMyInstitutions` здесь не нужен.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount, CurrencyTransaction } from '../api/currency'
import { ApiError } from '../api/errors'
import * as groupsApi from '../api/groups'
import type { Group } from '../api/groups'
import * as marketApi from '../api/market'
import type { Purchase } from '../api/market'
import * as studentsApi from '../api/students'
import type { StudentMember } from '../api/students'
import { useAuth } from '../auth/authContext'
import { useCurrencyName } from '../auth/useCurrencyName'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FieldError } from '../components/FieldError'
import { FormError } from '../components/FormError'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { SavedNotice } from '../components/SavedNotice'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { PURCHASE_STATUS_LABELS, ROLE_LABELS, STATUS_LABELS, TRANSACTION_KIND_LABELS } from '../i18n/labels'
import { randomOperationId } from '../utils/uuid'

function authorLabel(transaction: CurrencyTransaction): string {
  return transaction.created_by_name ?? ROLE_LABELS[transaction.created_by_role]
}

export function StudentCurrencyPage() {
  const { id, userId } = useParams<{ id: string; userId: string }>()
  const { token, institution } = useAuth()
  const currencyName = useCurrencyName()
  const isAdmin = institution?.role === 'institution_admin'

  const [students, setStudents] = useState<StudentMember[] | null>(null)
  const [studentsError, setStudentsError] = useState<unknown>(null)
  const [studentsAttempt, setStudentsAttempt] = useState(0)

  const [groups, setGroups] = useState<Group[] | null>(null)

  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [purchases, setPurchases] = useState<Purchase[] | null>(null)
  const [purchasesError, setPurchasesError] = useState<unknown>(null)

  const [amount, setAmount] = useState('')
  const [comment, setComment] = useState('')
  const [operationId, setOperationId] = useState(() => randomOperationId())
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<ApiError | null>(null)
  const [accrued, setAccrued] = useState(false)

  const [reverseTarget, setReverseTarget] = useState<CurrencyTransaction | null>(null)
  const [reversing, setReversing] = useState(false)
  const [reverseError, setReverseError] = useState<unknown>(null)

  // Поле имени — неконтролируемое (`ref` + `key={student.user_id}`), а не
  // `useState` с синхронизацией через эффект: имя приходит асинхронно из
  // `GET /students`, и `setState` внутри эффекта на каждую его загрузку —
  // лишний повторный рендер там, где достаточно сброса поля при монтировании.
  const nameInputRef = useRef<HTMLInputElement>(null)
  const [savingName, setSavingName] = useState(false)
  const [nameError, setNameError] = useState<unknown>(null)
  const [nameSaved, setNameSaved] = useState(false)

  const [suspendOpen, setSuspendOpen] = useState(false)
  const [savingStatus, setSavingStatus] = useState(false)
  const [statusError, setStatusError] = useState<unknown>(null)

  const [addGroupId, setAddGroupId] = useState('')
  const [groupBusy, setGroupBusy] = useState(false)
  const [groupError, setGroupError] = useState<unknown>(null)

  // Имя, статус и группы — из общего списка, отдельного запроса на одного
  // ученика в контракте нет.
  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    studentsApi
      .listStudents(token, id)
      .then((loaded) => {
        if (!cancelled) setStudents(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setStudentsError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, studentsAttempt])

  useEffect(() => {
    if (token === null || id === undefined || !isAdmin) return
    groupsApi
      .listGroups(token, id)
      .then(setGroups)
      .catch(() => undefined)
  }, [token, id, isAdmin, studentsAttempt])

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

  useEffect(() => {
    if (token === null || id === undefined || userId === undefined || !isAdmin) return
    let cancelled = false
    marketApi
      .listPurchases(token, id, { user_id: userId })
      .then((loaded) => {
        if (!cancelled) setPurchases(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setPurchasesError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, userId, isAdmin, attempt])

  const student = students?.find((member) => member.user_id === userId) ?? null

  function retry() {
    setAccount(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  function reloadStudent() {
    setStudentsAttempt((value) => value + 1)
  }

  async function handleAccrue(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined || userId === undefined) return
    setSubmitting(true)
    setFormError(null)
    setAccrued(false)
    try {
      await currencyApi.accrue(token, id, userId, {
        operation_id: operationId,
        amount: Number(amount),
        comment: comment.trim() === '' ? null : comment,
      })
      setAmount('')
      setComment('')
      setOperationId(randomOperationId())
      setAccrued(true)
      retry()
    } catch (caught) {
      setFormError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setSubmitting(false)
    }
  }

  async function handleReverse() {
    if (token === null || id === undefined || reverseTarget === null) return
    setReversing(true)
    setReverseError(null)
    try {
      await currencyApi.reverse(token, id, reverseTarget.id, randomOperationId())
      setReverseTarget(null)
      retry()
    } catch (caught) {
      setReverseError(caught)
    } finally {
      setReversing(false)
    }
  }

  async function handleSaveName() {
    if (token === null || id === undefined || userId === undefined) return
    const trimmed = (nameInputRef.current?.value ?? '').trim()
    if (trimmed === '') return
    setSavingName(true)
    setNameError(null)
    setNameSaved(false)
    try {
      await studentsApi.updateStudent(token, id, userId, { display_name: trimmed })
      setNameSaved(true)
      reloadStudent()
    } catch (caught) {
      setNameError(caught)
    } finally {
      setSavingName(false)
    }
  }

  async function applyStatus(status: StudentMember['status']) {
    if (token === null || id === undefined || userId === undefined) return
    setSavingStatus(true)
    setStatusError(null)
    try {
      await studentsApi.updateStudent(token, id, userId, { status })
      reloadStudent()
    } catch (caught) {
      setStatusError(caught)
    } finally {
      setSavingStatus(false)
    }
  }

  function handleStatusChange(status: StudentMember['status']) {
    if (status === 'suspended') {
      setSuspendOpen(true)
      return
    }
    void applyStatus(status)
  }

  async function confirmSuspend() {
    await applyStatus('suspended')
    setSuspendOpen(false)
  }

  async function handleAddGroup() {
    if (token === null || id === undefined || userId === undefined || addGroupId === '') return
    setGroupBusy(true)
    setGroupError(null)
    try {
      await groupsApi.addStudentToGroup(token, id, addGroupId, userId)
      setAddGroupId('')
      reloadStudent()
    } catch (caught) {
      setGroupError(caught)
    } finally {
      setGroupBusy(false)
    }
  }

  // Убрать из группы — без подтверждения (раздел 7, обратимо).
  async function handleRemoveGroup(groupId: string) {
    if (token === null || id === undefined || userId === undefined) return
    setGroupBusy(true)
    setGroupError(null)
    try {
      await groupsApi.removeStudentFromGroup(token, id, groupId, userId)
      reloadStudent()
    } catch (caught) {
      setGroupError(caught)
    } finally {
      setGroupBusy(false)
    }
  }

  const fieldErrors = formError?.fieldErrors

  const reversedIds = new Set(
    (account?.transactions ?? [])
      .filter((transaction) => transaction.kind === 'reversal' && transaction.reverses_id !== null)
      .map((transaction) => transaction.reverses_id as string),
  )

  function canReverse(transaction: CurrencyTransaction): boolean {
    return isAdmin && transaction.kind === 'manual_accrual' && !reversedIds.has(transaction.id)
  }

  const studentName = student?.display_name ?? 'Без имени'
  const studentGroups = student?.group_ids ?? []
  const availableGroups = (groups ?? []).filter((group) => !studentGroups.includes(group.id))

  if (studentsError !== null) {
    return (
      <main className="page">
        <PageHeader
          title="Ученик"
          crumbs={[{ label: 'Ученики', to: `/institutions/${id}/students` }]}
          institutionName={institution?.name}
        />
        <ScreenState state="error" error={studentsError} onRetry={reloadStudent} />
      </main>
    )
  }

  return (
    <main className="page">
      <PageHeader
        title={students === null ? 'Ученик' : studentName}
        crumbs={[{ label: 'Ученики', to: `/institutions/${id}/students` }]}
        institutionName={institution?.name}
      />

      {students === null && <ScreenState state="loading" />}

      {students !== null && student === null && <p>Ученик не найден.</p>}

      {student !== null && (
        <>
          {isAdmin && (
            <div className="field">
              <label htmlFor="student-name">Имя</label>
              <input
                key={student.user_id}
                ref={nameInputRef}
                id="student-name"
                type="text"
                maxLength={100}
                placeholder="Без имени"
                defaultValue={student.display_name ?? ''}
                disabled={savingName}
              />
              <button type="button" onClick={() => void handleSaveName()} disabled={savingName}>
                {savingName ? 'Сохраняем…' : 'Сохранить имя'}
              </button>
              <SavedNotice show={nameSaved} />
              <FormError message={nameError === null ? undefined : messageForError(nameError)} />
            </div>
          )}

          <p>
            Статус:{' '}
            {isAdmin ? (
              <select
                aria-label="Статус"
                value={student.status}
                onChange={(event) => handleStatusChange(event.target.value as StudentMember['status'])}
                disabled={savingStatus}
              >
                {(['active', 'suspended'] satisfies StudentMember['status'][]).map((option) => (
                  <option key={option} value={option}>
                    {STATUS_LABELS[option]}
                  </option>
                ))}
              </select>
            ) : (
              STATUS_LABELS[student.status]
            )}
          </p>
          <FormError message={statusError === null ? undefined : messageForError(statusError)} />

          <p>Группы: {studentGroups.length === 0 ? 'без группы' : undefined}</p>
          {studentGroups.length > 0 && (
            <ul className="institution-list">
              {studentGroups.map((groupId) => {
                const group = groups?.find((item) => item.id === groupId)
                return (
                  <li key={groupId} className="institution-item">
                    <p className="institution-name">{group?.name ?? '—'}</p>
                    {isAdmin && (
                      <button type="button" onClick={() => void handleRemoveGroup(groupId)} disabled={groupBusy}>
                        Убрать
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
          {isAdmin && groups !== null && availableGroups.length > 0 && (
            <div className="field">
              <label htmlFor="add-group">Добавить в группу</label>
              <select id="add-group" value={addGroupId} onChange={(event) => setAddGroupId(event.target.value)}>
                <option value="">Выберите…</option>
                {availableGroups.map((group) => (
                  <option key={group.id} value={group.id}>
                    {group.name}
                  </option>
                ))}
              </select>
              <button type="button" onClick={() => void handleAddGroup()} disabled={addGroupId === '' || groupBusy}>
                Добавить
              </button>
            </div>
          )}
          <FormError message={groupError === null ? undefined : messageForError(groupError)} />

          <form className="form" onSubmit={handleAccrue} noValidate>
            <h2>Начислить {currencyName}</h2>
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
            <SavedNotice show={accrued} text="Начислено" />
          </form>

          {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}
          {loadError === null && account === null && <ScreenState state="loading" />}

          {account !== null && (
            <>
              <p>
                Баланс: <Money amount={account.balance} size={20} />
              </p>

              {account.transactions.length === 0 && (
                <ScreenState state="empty" message="Операций пока нет." />
              )}

              {account.transactions.length > 0 && (
                <ul className="institution-list">
                  {account.transactions.map((transaction) => (
                    <li key={transaction.id} className="institution-item">
                      <div>
                        <p className="institution-name">
                          {TRANSACTION_KIND_LABELS[transaction.kind]}:{' '}
                          <Money amount={transaction.amount} showPlus />
                        </p>
                        <p className="institution-meta">
                          {authorLabel(transaction)} ·{' '}
                          {new Date(transaction.created_at).toLocaleString('ru-RU')}
                          {transaction.comment !== null && transaction.comment !== ''
                            ? ` · ${transaction.comment}`
                            : ''}
                        </p>
                      </div>
                      {canReverse(transaction) && (
                        <button type="button" onClick={() => setReverseTarget(transaction)}>
                          Сторно
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}

          {isAdmin && (
            <>
              <h2>Покупки</h2>
              {purchasesError !== null && (
                <ScreenState
                  state="error"
                  error={purchasesError}
                  onRetry={() => setAttempt((value) => value + 1)}
                />
              )}
              {purchasesError === null && purchases === null && <ScreenState state="loading" />}
              {purchasesError === null && purchases !== null && purchases.length === 0 && (
                <ScreenState state="empty" message="Покупок пока нет." />
              )}
              {purchases !== null && purchases.length > 0 && (
                <ul className="institution-list">
                  {purchases.map((purchase) => (
                    <li key={purchase.id} className="institution-item">
                      <div>
                        <p className="institution-name">{purchase.title}</p>
                        <p className="institution-meta">
                          {PURCHASE_STATUS_LABELS[purchase.status]} ·{' '}
                          {new Date(purchase.created_at).toLocaleString('ru-RU')}
                        </p>
                      </div>
                      <Money amount={-purchase.price} />
                    </li>
                  ))}
                </ul>
              )}
              <p>
                <Link to={`/institutions/${id}/purchases`}>Все заявки учреждения</Link>
              </p>
            </>
          )}
        </>
      )}

      <ConfirmDialog
        open={reverseTarget !== null}
        title="Сторнировать начисление?"
        description={
          reverseTarget !== null ? (
            <>
              <Money amount={reverseTarget.amount} showPlus /> — {studentName}
            </>
          ) : undefined
        }
        confirmLabel="Сторнировать"
        danger
        pending={reversing}
        onConfirm={() => void handleReverse()}
        onClose={() => setReverseTarget(null)}
      />
      {reverseError !== null && <FormError message={messageForError(reverseError)} />}

      <ConfirmDialog
        open={suspendOpen}
        title="Приостановить ученика?"
        description="Доступ пропадёт сразу."
        confirmLabel="Приостановить"
        danger
        pending={savingStatus}
        onConfirm={() => void confirmSuspend()}
        onClose={() => setSuspendOpen(false)}
      />
    </main>
  )
}
