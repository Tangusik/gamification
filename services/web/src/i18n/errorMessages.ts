/**
 * Человеческие тексты для машинных кодов ошибок.
 *
 * Коды приходят с сервера и не локализуются — локализуется только эта карта.
 * Незнакомый код не должен приводить к пустому экрану: для него есть запасной
 * текст, а сам код показывается рядом, чтобы его можно было назвать в
 * поддержке.
 */
import { ApiError, NETWORK_ERROR, UNKNOWN_ERROR, VALIDATION_ERROR } from '../api/errors'

const MESSAGES: Record<string, string> = {
  // Сеть и общее
  [NETWORK_ERROR]: 'Сервер недоступен. Проверьте соединение и попробуйте ещё раз.',
  [UNKNOWN_ERROR]: 'Непредвиденная ошибка. Попробуйте ещё раз.',
  [VALIDATION_ERROR]: 'Проверьте правильность заполнения полей.',

  // Регистрация и вход
  REGISTER_USER_ALREADY_EXISTS: 'Пользователь с такой почтой уже зарегистрирован.',
  REGISTER_INVALID_PASSWORD: 'Пароль не подходит: слишком короткий или слишком простой.',
  LOGIN_BAD_CREDENTIALS: 'Неверная почта или пароль.',
  LOGIN_USER_NOT_VERIFIED: 'Почта не подтверждена.',

  // Доступ
  Unauthorized: 'Сессия истекла. Войдите заново.',
  AUTH_REQUIRED: 'Сессия истекла. Войдите заново.',
  INSTITUTION_CONTEXT_REQUIRED: 'Сначала выберите учреждение.',
  NOT_A_MEMBER: 'Учреждение недоступно: членство не активно.',
  INSUFFICIENT_ROLE: 'Недостаточно прав для этого действия.',
  MEMBERSHIP_SUSPENDED: 'Участие в учреждении приостановлено.',

  // Приглашения и выпуск токена
  INVITATION_INVALID: 'Ссылка приглашения недействительна. Попросите новую.',
  TOKEN_ISSUER_UNAVAILABLE:
    'Сервис временно недоступен. Текущий вход сохраняется, повторите попытку позже.',

  // Смена пароля
  UPDATE_USER_INVALID_PASSWORD: 'Пароль не подходит: слишком короткий или слишком простой.',

  // Преподаватели, ученики, группы (администратор учреждения)
  EMAIL_ALREADY_REGISTERED: 'Пользователь с такой почтой уже зарегистрирован.',
  INVALID_PASSWORD: 'Пароль не подходит: слишком короткий или слишком простой.',
  MEMBER_NOT_FOUND: 'Участник не найден.',
  GROUP_NOT_FOUND: 'Группа не найдена.',
  GROUP_NAME_TAKEN: 'Группа с таким названием уже есть.',
  USERS_UNAVAILABLE: 'Сервис пользователей временно недоступен. Попробуйте позже.',
  USERS_CONTRACT_ERROR: 'Непредвиденная ошибка сервиса пользователей.',

  // Валюта
  STUDENT_SUSPENDED: 'Участие ученика приостановлено, начисление недоступно.',
  OPERATION_ID_CONFLICT: 'Операция уже была отправлена с другими данными. Обновите страницу.',
  TRANSACTION_NOT_FOUND: 'Операция не найдена.',
  TRANSACTION_ALREADY_REVERSED: 'Начисление уже сторнировано.',

  // Маркет привилегий
  PRIVILEGE_NOT_FOUND: 'Привилегия не найдена.',
  PURCHASE_NOT_FOUND: 'Покупка не найдена.',
  OUT_OF_STOCK: 'Позиция закончилась.',
  PRICE_CHANGED: 'Цена изменилась. Каталог обновлён — проверьте актуальную цену.',
  INSUFFICIENT_BALANCE: 'Недостаточно средств на балансе.',
  CONCURRENT_UPDATE:
    'Операцию не удалось выполнить из-за одновременного изменения данных. Повторите запрос.',
  PURCHASE_ALREADY_RESOLVED: 'Покупка уже обработана.',
}

const FALLBACK = 'Не удалось выполнить запрос.'

/** Текст для кода ошибки; для незнакомого кода — запасной с самим кодом. */
export function messageForCode(code: string): string {
  return MESSAGES[code] ?? `${FALLBACK} (${code})`
}

/** Текст для ошибки запроса. */
export function messageForError(error: unknown): string {
  if (error instanceof ApiError) {
    return messageForCode(error.code)
  }
  return FALLBACK
}
