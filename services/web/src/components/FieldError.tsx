/** Сообщение об ошибке рядом с полем формы. */
type Props = { message?: string }

export function FieldError({ message }: Props) {
  if (message === undefined) return null
  return <span className="field-error">{message}</span>
}
