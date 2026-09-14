/**
 * Разбор ответа API в единую ошибку.
 *
 * Контракт сервиса: тело ошибки всегда `{"detail": "MACHINE_READABLE_CODE"}`.
 * Единственное исключение — 422 от валидации FastAPI: там список ошибок по
 * полям, и схлопывать его нельзя, иначе форма потеряет информацию о том,
 * какое именно поле неверно.
 */

/** Ошибки по именам полей формы: `email` → текст от сервера. */
export type FieldErrors = Record<string, string>

export class ApiError extends Error {
  readonly status: number
  /** Машинный код из `detail`; для 422 — `VALIDATION_ERROR`. */
  readonly code: string
  readonly fieldErrors?: FieldErrors

  constructor(status: number, code: string, fieldErrors?: FieldErrors) {
    super(code)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fieldErrors = fieldErrors
  }
}

/** Код, который клиент подставляет, когда запрос не дошёл до сервера. */
export const NETWORK_ERROR = 'NETWORK_ERROR'
/** Код 422: подробности лежат в `fieldErrors`. */
export const VALIDATION_ERROR = 'VALIDATION_ERROR'
/** Ответ не разобрался — тело не JSON или не соответствует контракту. */
export const UNKNOWN_ERROR = 'UNKNOWN_ERROR'

/** Требуется контекст учреждения — повод увести на выбор учреждения. */
export const INSTITUTION_CONTEXT_REQUIRED = 'INSTITUTION_CONTEXT_REQUIRED'

type ValidationItem = {
  loc?: unknown[]
  msg?: string
}

/**
 * Собрать карту «поле → сообщение» из тела 422.
 *
 * `loc` выглядит как `["body", "email"]`; именем поля считается последний
 * строковый элемент, потому что вложенных тел у форм этого этапа нет.
 */
function parseFieldErrors(detail: unknown): FieldErrors | undefined {
  if (!Array.isArray(detail)) return undefined

  const result: FieldErrors = {}
  for (const raw of detail) {
    const item = raw as ValidationItem
    const loc = Array.isArray(item.loc) ? item.loc : []
    const field = [...loc].reverse().find((part) => typeof part === 'string')
    if (typeof field === 'string' && typeof item.msg === 'string') {
      result[field] = item.msg
    }
  }
  return Object.keys(result).length > 0 ? result : undefined
}

/**
 * Превратить неуспешный ответ в `ApiError`, не бросая на нечитаемом теле.
 *
 * Функция синхронная и чистая: тело приходит уже разобранным (axios делает
 * это сам), поэтому разбирать поток здесь больше не нужно. Незнакомая форма
 * тела — не повод бросать исключение внутри обработчика ошибок: тогда
 * настоящая ошибка потерялась бы за вторичной.
 */
export function toApiError(status: number, body: unknown): ApiError {
  const detail =
    body !== null && typeof body === 'object' && 'detail' in body
      ? (body as { detail: unknown }).detail
      : undefined

  if (status === 422) {
    return new ApiError(422, VALIDATION_ERROR, parseFieldErrors(detail))
  }
  if (typeof detail === 'string' && detail.length > 0) {
    return new ApiError(status, detail)
  }
  return new ApiError(status, UNKNOWN_ERROR)
}
