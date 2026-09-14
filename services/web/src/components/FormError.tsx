/** Сообщение об ошибке для формы целиком. */
type Props = { message?: string }

export function FormError({ message }: Props) {
  if (message === undefined) return null
  return (
    <p className="form-error" role="alert">
      {message}
    </p>
  )
}
