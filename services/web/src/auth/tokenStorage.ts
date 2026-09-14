/**
 * Единственное место, где живёт access-токен.
 *
 * Хранилище — `localStorage`: cookie-транспорта у бэкенда нет
 * (fastapi-users настроен на Bearer), а хранение только в памяти означало бы
 * разлогин на каждом F5. Риск XSS принят осознанно и ограничен сроком жизни
 * токена. Точка возврата — появление refresh-сессий: тогда меняется этот
 * модуль, и только он.
 */

const TOKEN_KEY = 'gamification.accessToken'
/** Id учреждения, выбранного в прошлый раз — для автовыбора при входе и на F5. */
const LAST_INSTITUTION_KEY = 'gamification.lastInstitutionId'

export function get(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_KEY)
  } catch {
    // Приватный режим браузера может запрещать доступ к хранилищу.
    return null
  }
}

export function set(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // Нечего делать: сессия проживёт до перезагрузки страницы.
  }
}

export function clear(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(LAST_INSTITUTION_KEY)
  } catch {
    // См. выше.
  }
}

export function getLastInstitutionId(): string | null {
  try {
    return window.localStorage.getItem(LAST_INSTITUTION_KEY)
  } catch {
    return null
  }
}

export function setLastInstitutionId(institutionId: string): void {
  try {
    window.localStorage.setItem(LAST_INSTITUTION_KEY, institutionId)
  } catch {
    // Нечего делать: выбор не переживёт перезагрузку в приватном режиме.
  }
}
