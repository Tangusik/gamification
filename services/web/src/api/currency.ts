/**
 * Валюта: баланс, история операций, ручное начисление и сторно.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import type { UserRole } from './auth'
import { request } from './client'

/**
 * `purchase` и `purchase_refund` — записи маркета (план `07-market.md`, Ч1):
 * списание при покупке и возврат при отказе админа. Бэкенд ещё не сделан,
 * добавлено по контракту, чтобы `labels.ts` типизировался без `as`.
 */
export type TransactionKind = 'manual_accrual' | 'reversal' | 'purchase' | 'purchase_refund'

export type CurrencyTransaction = {
  id: string
  kind: TransactionKind
  /** У сторно (`reversal`) отрицательный. */
  amount: number
  comment: string | null
  /** `null`, если у автора нет имени — тогда показывается роль. */
  created_by_name: string | null
  created_by_role: UserRole
  created_at: string
  /** У сторно — id начисления, которое оно отменяет; иначе `null`. */
  reverses_id: string | null
}

export type CurrencyAccount = {
  balance: number
  /** Последние 50 операций, новые сверху. */
  transactions: CurrencyTransaction[]
}

export type AccrueInput = {
  operation_id: string
  amount: number
  comment?: string | null
}

function institutionPath(institutionId: string): string {
  return `/institutions/${encodeURIComponent(institutionId)}`
}

/** Баланс и история текущего пользователя — доступно только `student`. */
export function getMyCurrency(token: string, institutionId: string): Promise<CurrencyAccount> {
  return request<CurrencyAccount>(`${institutionPath(institutionId)}/me/currency`, { token })
}

/** Баланс и история одного ученика — доступно `teacher` и `institution_admin`. */
export function listStudentTransactions(
  token: string,
  institutionId: string,
  userId: string,
): Promise<CurrencyAccount> {
  return request<CurrencyAccount>(
    `${institutionPath(institutionId)}/students/${encodeURIComponent(userId)}/currency-transactions`,
    { token },
  )
}

/**
 * Начислить валюту ученику. Идемпотентно по `operation_id`: повтор того же
 * запроса возвращает уже созданную запись (сервер отвечает 200 вместо 201),
 * для вызывающего кода разница не важна — тело ответа одно и то же.
 */
export function accrue(
  token: string,
  institutionId: string,
  userId: string,
  input: AccrueInput,
): Promise<CurrencyTransaction> {
  return request<CurrencyTransaction>(
    `${institutionPath(institutionId)}/students/${encodeURIComponent(userId)}/currency-transactions`,
    { method: 'POST', json: input, token },
  )
}

/** Сторнировать начисление — доступно только `institution_admin`. */
export function reverse(
  token: string,
  institutionId: string,
  transactionId: string,
  operationId: string,
): Promise<CurrencyTransaction> {
  return request<CurrencyTransaction>(
    `${institutionPath(institutionId)}/currency-transactions/${encodeURIComponent(transactionId)}/reversal`,
    { method: 'POST', json: { operation_id: operationId }, token },
  )
}
