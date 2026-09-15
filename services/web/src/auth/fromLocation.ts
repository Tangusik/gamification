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

/**
 * Пути, с которых неавторизованного пользователя ведёт сразу на регистрацию,
 * а не на вход. Сейчас только `/invite`: ссылку-приглашение обычно открывает
 * новый ученик без аккаунта (В16 плана `08-web-ux-and-deploy.md`).
 */
const REGISTER_FIRST_PATHS = new Set(['/invite'])

/**
 * Куда вести неавторизованного пользователя `RequireAuth` — чистая функция,
 * вынесенная отдельно ради теста без рендера роутера.
 */
export function anonRedirectTarget(pathname: string): '/login' | '/register' {
  return REGISTER_FIRST_PATHS.has(pathname) ? '/register' : '/login'
}
