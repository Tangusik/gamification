/**
 * Точка входа в разделы администрирования учреждения — `/institutions/:id/manage`.
 *
 * Контекст токена уже совпадает с `:id`: маршрут защищён `RequireInstitution`,
 * который переключиться сюда не пускает без совпадения. Переходы между
 * разделами внутри учреждения дальше — обычные ссылки: смены контекста не
 * требуют.
 *
 * Название учреждения — из контекста (`useAuth().institution`), а не из
 * `location.state`: так оно не теряется на F5.
 *
 * Счётчик у «Покупки» — число заявок `pending` (N1, план `07-market.md`).
 * Запрос безопасен именно здесь: контекст токена уже совпадает с `:id`
 * (в отличие от `InstitutionsPage`, где для другого учреждения он дал бы
 * `INSTITUTION_CONTEXT_REQUIRED`). Ошибка загрузки счётчика молча гасится —
 * ссылка остаётся рабочей и без числа, актуальную очередь показывает сама
 * `PurchasesPage`.
 */
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import * as marketApi from '../api/market'
import { useAuth } from '../auth/authContext'

export function InstitutionManagePage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const institutionName = institution?.name

  const [pendingCount, setPendingCount] = useState<number | null>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listPurchases(token, id, { status: 'pending' })
      .then((loaded) => {
        if (!cancelled) setPendingCount(loaded.length)
      })
      .catch(() => undefined)
    return () => {
      cancelled = true
    }
  }, [token, id])

  if (id === undefined) return null

  return (
    <>
      <main className="page">
        <h1>Управление{institutionName !== undefined ? ` — ${institutionName}` : ''}</h1>

        <ul className="institution-list">
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/teachers`}>Преподаватели</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/groups`}>Группы</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/students`}>Ученики</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/invitations`}>Приглашения</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/currency`}>Начисления</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/privileges`}>Каталог привилегий</Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/purchases`}>
                Покупки{pendingCount !== null ? ` (${pendingCount})` : ''}
              </Link>
            </p>
          </li>
          <li className="institution-item">
            <p className="institution-name">
              <Link to={`/institutions/${id}/settings`}>Настройки</Link>
            </p>
          </li>
        </ul>
      </main>
    </>
  )
}
