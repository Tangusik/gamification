/**
 * Диалог подтверждения на нативном `<dialog>` — не `window.confirm` (раздел 7
 * плана `08-web-ux-and-deploy.md`).
 *
 * `<dialog>` сам закрывается по Esc (событие `cancel`) и сам управляет
 * фокусом внутри модалки; по умолчанию фокус ставим на «Отмена» —
 * безопасное действие для опасных подтверждений.
 */
import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

type Props = {
  open: boolean
  title: string
  description?: ReactNode
  /** Подпись кнопки называет само действие, а не «ОК» — например, «Удалить группу». */
  confirmLabel: string
  cancelLabel?: string
  /** Опасное действие — кнопка подтверждения цветом danger. */
  danger?: boolean
  /** Блокирует обе кнопки на время запроса. */
  pending?: boolean
  onConfirm: () => void
  onClose: () => void
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = 'Отмена',
  danger = false,
  pending = false,
  onConfirm,
  onClose,
}: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog === null) return

    if (open && !dialog.open) {
      dialog.showModal()
      cancelRef.current?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  return (
    <dialog
      ref={dialogRef}
      className="confirm-dialog"
      // `cancel` — родное событие `<dialog>` по Esc.
      onCancel={onClose}
      onClose={onClose}
      aria-labelledby="confirm-dialog-title"
    >
      <h2 id="confirm-dialog-title" className="confirm-dialog-title">
        {title}
      </h2>
      {description !== undefined && <div className="confirm-dialog-description">{description}</div>}
      <div className="confirm-dialog-actions">
        <button ref={cancelRef} type="button" onClick={onClose} disabled={pending}>
          {cancelLabel}
        </button>
        <button type="button" className={danger ? 'danger' : undefined} onClick={onConfirm} disabled={pending}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  )
}
