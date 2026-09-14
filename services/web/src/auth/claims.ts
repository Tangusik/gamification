/**
 * Разбор claim `institution_id` из access-токена — только для UI.
 *
 * Подпись не проверяется и не может: токен уже проверен сервером на каждом
 * запросе, здесь он нужен лишь для мгновенного рендера текущего учреждения
 * без лишнего запроса. Источник истины по роли и названию — свежий
 * `GET /institutions` в `AuthProvider`, сам claim может отставать от него
 * до 900 секунд (время жизни токена). Формат — общий контракт,
 * `libs/gamification-auth/gamification_auth/claims.py`.
 */

/** Достать `institution_id` из access-токена; `null`, если его нет или токен не разобрать. */
export function decodeInstitutionId(token: string): string | null {
  const payload = decodePayload(token)
  const value = payload?.institution_id
  return typeof value === 'string' ? value : null
}

function decodePayload(token: string): Record<string, unknown> | null {
  const part = token.split('.')[1]
  if (part === undefined) return null
  try {
    const base64 = part.replaceAll('-', '+').replaceAll('_', '/')
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=')
    // atob декодирует по code unit, а не по UTF-8 байту — для нужных здесь
    // claims (UUID учреждения) этого достаточно, они всегда ASCII.
    const json = window.atob(padded)
    const parsed: unknown = JSON.parse(json)
    return typeof parsed === 'object' && parsed !== null ? (parsed as Record<string, unknown>) : null
  } catch {
    return null
  }
}
