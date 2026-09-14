/**
 * Путь возврата после входа/регистрации, сохранённый `RequireAuth` в
 * `state.from`.
 *
 * `location.state.from` — это полный объект `Location`, включая `hash`: его
 * нельзя терять, иначе аноним, открывший `/invite#<token>`, после входа
 * потеряет токен приглашения — он живёт только во фрагменте, на сервер не
 * уходит и в `pathname` не переносится.
 */
import type { Location } from 'react-router'

export type FromState = { from?: Pick<Location, 'pathname' | 'search' | 'hash'> }

/** Собрать путь для `navigate()` из состояния роутера; по умолчанию — `/`. */
export function targetFromState(state: unknown): string {
  const from = (state as FromState | null)?.from
  if (from?.pathname === undefined) return '/'
  return `${from.pathname}${from.search}${from.hash}`
}
