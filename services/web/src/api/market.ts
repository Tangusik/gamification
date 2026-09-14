/**
 * Маркет привилегий: каталог, покупки и очередь решений.
 *
 * Бэкенд ещё не написан (план `.claude/plans/07-market.md`, Ч2 ведётся
 * параллельно с Ч1) — типы и пути собраны по контракту из раздела Ч1 (таблица
 * эндпоинтов), живых проверок не было.
 *
 * Пути даны без завершающего слэша — см. правило в `client.ts`.
 */
import { request } from './client'

export type Privilege = {
  id: string
  title: string
  description: string | null
  price: number
  /** `null` — без ограничения (L2). */
  stock: number | null
  is_active: boolean
}

export type CreatePrivilegeInput = {
  title: string
  description?: string | null
  price: number
  stock?: number | null
  is_active?: boolean
}

/**
 * Любые поля необязательны (У11): сервер различает «поле не передано» и
 * `stock: null` (явная очистка до «без ограничения») через
 * `model_fields_set`, поэтому непереданные поля не должны попадать в тело
 * запроса вовсе — вызывающий код обязан формировать объект только из
 * изменившихся полей.
 */
export type UpdatePrivilegeInput = Partial<{
  title: string
  description: string | null
  price: number
  stock: number | null
  is_active: boolean
}>

export type PurchaseStatus = 'pending' | 'fulfilled' | 'rejected'

/**
 * Форма покупки в плане не зафиксирована («Форма объекта покупки в плане не
 * зафиксирована»). Собрана из модели данных (Ч1, раздел «Модель»):
 * `title`/`price` — снимок на момент покупки (У4), `resolved_at` — `null`
 * до решения. `user_id`/`user_name` добавлены минимально для админского
 * списка («для админского списка разумно ожидать идентификатор/имя
 * ученика») — сделаны необязательными, чтобы не утверждать про форму
 * ответа `GET /me/purchases`, где они, вероятно, не нужны.
 */
export type Purchase = {
  id: string
  privilege_id: string
  title: string
  price: number
  status: PurchaseStatus
  created_at: string
  resolved_at: string | null
  user_id?: string
  user_name?: string | null
}

export type PurchaseInput = {
  operation_id: string
  privilege_id: string
  expected_price: number
}

export type ListPurchasesFilter = {
  status?: PurchaseStatus
  user_id?: string
}

function institutionPath(institutionId: string): string {
  return `/institutions/${encodeURIComponent(institutionId)}`
}

/** Каталог привилегий: ученик и преподаватель видят только активные, админ — все. */
export function listPrivileges(token: string, institutionId: string): Promise<Privilege[]> {
  return request<Privilege[]>(`${institutionPath(institutionId)}/privileges`, { token })
}

/** Создать позицию каталога — доступно только `institution_admin`. */
export function createPrivilege(
  token: string,
  institutionId: string,
  input: CreatePrivilegeInput,
): Promise<Privilege> {
  return request<Privilege>(`${institutionPath(institutionId)}/privileges`, {
    method: 'POST',
    json: input,
    token,
  })
}

/** Изменить позицию каталога — доступно только `institution_admin`. */
export function updatePrivilege(
  token: string,
  institutionId: string,
  privilegeId: string,
  input: UpdatePrivilegeInput,
): Promise<Privilege> {
  return request<Privilege>(
    `${institutionPath(institutionId)}/privileges/${encodeURIComponent(privilegeId)}`,
    { method: 'PATCH', json: input, token },
  )
}

/**
 * Купить привилегию — доступно только `student`. Идемпотентно по
 * `operation_id`: повтор того же тела возвращает уже созданную покупку
 * (сервер отвечает 200 вместо 201), для вызывающего кода разница не важна.
 */
export function purchase(
  token: string,
  institutionId: string,
  input: PurchaseInput,
): Promise<Purchase> {
  return request<Purchase>(`${institutionPath(institutionId)}/purchases`, {
    method: 'POST',
    json: input,
    token,
  })
}

/** Свои покупки — последние 50, доступно только `student`. */
export function listMyPurchases(token: string, institutionId: string): Promise<Purchase[]> {
  return request<Purchase[]>(`${institutionPath(institutionId)}/me/purchases`, { token })
}

/**
 * Покупки учреждения — доступно только `institution_admin`. `status:
 * 'pending'` отдаётся без лимита (У8), остальные фильтры — последние 50.
 */
export function listPurchases(
  token: string,
  institutionId: string,
  filter: ListPurchasesFilter = {},
): Promise<Purchase[]> {
  const params = new URLSearchParams()
  if (filter.status !== undefined) params.set('status', filter.status)
  if (filter.user_id !== undefined) params.set('user_id', filter.user_id)
  const query = params.toString()
  return request<Purchase[]>(
    `${institutionPath(institutionId)}/purchases${query === '' ? '' : `?${query}`}`,
    { token },
  )
}

/** Отметить покупку выданной — доступно только `institution_admin`, идемпотентно по статусу. */
export function fulfilPurchase(
  token: string,
  institutionId: string,
  purchaseId: string,
): Promise<Purchase> {
  return request<Purchase>(
    `${institutionPath(institutionId)}/purchases/${encodeURIComponent(purchaseId)}/fulfil`,
    { method: 'POST', token },
  )
}

/** Отклонить покупку — доступно только `institution_admin`, возвращает валюту и остаток. */
export function rejectPurchase(
  token: string,
  institutionId: string,
  purchaseId: string,
): Promise<Purchase> {
  return request<Purchase>(
    `${institutionPath(institutionId)}/purchases/${encodeURIComponent(purchaseId)}/reject`,
    { method: 'POST', token },
  )
}
