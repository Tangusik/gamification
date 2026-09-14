/**
 * Покупки — `/institutions/:id/purchases`, доступно только
 * `institution_admin` (У2). Очередь `pending` (N1 — обычный запрос при
 * открытии, без websocket и опроса по таймеру) со счётчиком в заголовке,
 * решение «Выдано»/«Отклонить», и история уже решённых покупок.
 *
 * Бэкенда маркета ещё нет — экран собран по контракту плана
 * `.claude/plans/07-market.md` (раздел Ч1), живых проверок не было.
 *
 * **История — минимальный вариант.** Отдельного фильтра «история» в
 * контракте нет: `GET /purchases` без `status` отдаёт последние 50 записей
 * вперемешку со статусами (У8). Второй отдельный запрос под каждый статус
 * ради истории был бы избыточен, поэтому здесь один запрос без `status`, а
 * очередь `pending` (которая отдаётся без лимита и своим отдельным запросом)
 * вычитается из него на клиенте — показываются только `fulfilled` и
 * `rejected`.
 */
import { useEffect, useState } from 'react'
import { useParams } from 'react-router'

import { ApiError } from '../api/errors'
import * as marketApi from '../api/market'
import type { Purchase } from '../api/market'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { PURCHASE_STATUS_LABELS } from '../i18n/labels'

export function PurchasesPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

  const [pending, setPending] = useState<Purchase[] | null>(null)
  const [pendingError, setPendingError] = useState<unknown>(null)

  const [recent, setRecent] = useState<Purchase[] | null>(null)
  const [recentError, setRecentError] = useState<unknown>(null)

  const [refreshKey, setRefreshKey] = useState(0)

  const [actingId, setActingId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<unknown>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listPurchases(token, id, { status: 'pending' })
      .then((loaded) => {
        if (!cancelled) setPending(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setPendingError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, refreshKey])

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listPurchases(token, id)
      .then((loaded) => {
        if (!cancelled) setRecent(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setRecentError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, refreshKey])

  function retry() {
    setPendingError(null)
    setRecentError(null)
    setRefreshKey((value) => value + 1)
  }

  async function handleFulfil(purchaseId: string) {
    if (token === null || id === undefined || actingId !== null) return
    setActingId(purchaseId)
    setActionError(null)
    try {
      await marketApi.fulfilPurchase(token, id, purchaseId)
      retry()
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setActingId(null)
    }
  }

  async function handleReject(purchaseId: string) {
    if (token === null || id === undefined || actingId !== null) return
    setActingId(purchaseId)
    setActionError(null)
    try {
      await marketApi.rejectPurchase(token, id, purchaseId)
      retry()
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setActingId(null)
    }
  }

  const history = (recent ?? []).filter((item) => item.status !== 'pending')

  return (
    <>
      <main className="page">
        <h1>Покупки{pending !== null ? ` (${pending.length})` : ''}</h1>

        {pendingError !== null && (
          <>
            <FormError message={messageForError(pendingError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {pendingError === null && pending === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {pending !== null && pending.length === 0 && <p>Заявок на решение нет.</p>}

        {pending !== null && pending.length > 0 && (
          <ul className="institution-list">
            {pending.map((item) => (
              <li key={item.id} className="institution-item">
                <div>
                  <p className="institution-name">
                    {item.title} — {item.price}
                  </p>
                  <p className="institution-meta">
                    {(item.user_name ?? item.user_id) !== undefined &&
                      `${item.user_name ?? item.user_id} · `}
                    {new Date(item.created_at).toLocaleString()}
                  </p>
                </div>
                <div>
                  <button
                    type="button"
                    onClick={() => void handleFulfil(item.id)}
                    disabled={actingId !== null}
                  >
                    {actingId === item.id ? 'Сохраняем…' : 'Выдано'}
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleReject(item.id)}
                    disabled={actingId !== null}
                  >
                    {actingId === item.id ? 'Сохраняем…' : 'Отклонить'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}

        {actionError !== null && <FormError message={messageForError(actionError)} />}

        <h2>История</h2>

        {recentError !== null && <FormError message={messageForError(recentError)} />}

        {recentError === null && recent === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {recent !== null && history.length === 0 && <p>Решённых покупок пока нет.</p>}

        {history.length > 0 && (
          <ul className="institution-list">
            {history.map((item) => (
              <li key={item.id} className="institution-item">
                <div>
                  <p className="institution-name">
                    {item.title} — {item.price}
                  </p>
                  <p className="institution-meta">
                    {(item.user_name ?? item.user_id) !== undefined &&
                      `${item.user_name ?? item.user_id} · `}
                    {PURCHASE_STATUS_LABELS[item.status]} ·{' '}
                    {item.resolved_at !== null && new Date(item.resolved_at).toLocaleString()}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </main>
    </>
  )
}
