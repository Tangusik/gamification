/**
 * Единственное место, где живёт access-токен.
 *
 * Access — в памяти модуля (У9 плана `10-refresh.md`): refresh-сессия теперь
 * лежит на сервере за httpOnly-cookie, и на F5 состояние восстанавливается
 * запросом `POST …/jwt/refresh` (`AuthProvider`), а не чтением токена из
 * хранилища. Хранить access в `localStorage`/`sessionStorage` больше незачем
 * и небезопаснее: доступный из JS access живёт до 15 минут и так, а вот
 * XSS-доступ к refresh (которого здесь и так нет — он httpOnly) не должен
 * появиться из-за этого модуля.
 */

/** Ключ, под которым access лежал в `localStorage` до refresh-сессий. */
const OLD_TOKEN_KEY = 'gamification.accessToken'
/** Id учреждения, выбранного в прошлый раз — для автовыбора при входе и на F5. */
const LAST_INSTITUTION_KEY = 'gamification.lastInstitutionId'

// Разовая уборка при загрузке модуля: старый ключ с access-токеном отсюда
// больше не читается и не пишется, но должен быть стёрт — иначе он бессмысленно
// остаётся висеть в браузере пользователя.
try {
  window.localStorage.removeItem(OLD_TOKEN_KEY)
} catch {
  // Приватный режим браузера может запрещать доступ к хранилищу.
}

let accessToken: string | null = null

export function get(): string | null {
  return accessToken
}

export function set(token: string): void {
  accessToken = token
}

export function clear(): void {
  accessToken = null
  try {
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
