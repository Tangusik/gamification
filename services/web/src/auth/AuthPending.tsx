/** Заглушка на время проверки токена: пока она видна, запросы не идут. */
export function AuthPending() {
  return (
    <p className="page-status" role="status">
      Загрузка…
    </p>
  )
}
