/**
 * Общий компонент трёх состояний экрана: загрузка, ошибка, пустота — плюс
 * отдельный вид «Нет доступа» для 403 `INSUFFICIENT_ROLE` (раздел 7 плана
 * `08-web-ux-and-deploy.md`). Текст ошибки берётся из
 * `src/i18n/errorMessages.ts`; для незнакомого кода она уже приписывает сам
 * код в скобках — здесь он только визуально уменьшается.
 */
import type { ReactNode } from 'react'

import { ApiError } from '../api/errors'
import { messageForError } from '../i18n/errorMessages'

type Props =
  | { state: 'loading' }
  | { state: 'error'; error: unknown; onRetry: () => void }
  | { state: 'empty'; message: string; action?: ReactNode }

/** `messageForError` для незнакомого кода возвращает `"текст (КОД)"` — здесь код визуально уменьшается. */
function splitUnknownCode(message: string): { text: string; code?: string } {
  const match = /^(.*) \(([A-Z0-9_]+)\)$/.exec(message)
  if (match === null) return { text: message }
  return { text: match[1], code: match[2] }
}

export function ScreenState(props: Props) {
  if (props.state === 'loading') {
    return (
      <p className="page-status" role="status">
        Загрузка…
      </p>
    )
  }

  if (props.state === 'error') {
    const isForbidden = props.error instanceof ApiError && props.error.code === 'INSUFFICIENT_ROLE'

    if (isForbidden) {
      return (
        <div className="screen-state" role="alert">
          <p className="screen-state-title">Нет доступа</p>
          <p>Недостаточно прав для этого действия.</p>
        </div>
      )
    }

    const { text, code } = splitUnknownCode(messageForError(props.error))
    return (
      <div className="screen-state" role="alert">
        <p>
          {text}
          {code !== undefined && <span className="screen-state-code"> ({code})</span>}
        </p>
        <button type="button" onClick={props.onRetry}>
          Повторить
        </button>
      </div>
    )
  }

  return (
    <div className="screen-state">
      <p>{props.message}</p>
      {props.action}
    </div>
  )
}
