/**
 * Заявки на выдачу — `/institutions/:id/purchases`, доступно только
 * `institution_admin`. Очередь `pending` (N1 — обычный запрос при открытии,
 * без websocket и опроса по таймеру) и история уже решённых покупок.
 * Счётчик заявок в меню обновляется сам при смене маршрута — здесь ничего
 * дополнительно не делается.
 *
 * Оба решения подтверждаются диалогом (В7, решение владельца против
 * рекомендации): «Отклонить» — валюта вернётся ученику; «Выдать» —
 * подтверждение прямо говорит, что отменить выдачу нельзя.
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
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FormError } from '../components/FormError'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { PURCHASE_STATUS_LABELS } from '../i18n/labels'

type PendingAction = { purchase: Purchase; kind: 'fulfil' | 'reject' }

export function PurchasesPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()

  const [pending, setPending] = useState<Purchase[] | null>(null)
  const [pendingError, setPendingError] = useState<unknown>(null)

  const [recent, setRecent] = useState<Purchase[] | null>(null)
  const [recentError, setRecentError] = useState<unknown>(null)

  const [refreshKey, setRefreshKey] = useState(0)

  const [action, setAction] = useState<PendingAction | null>(null)
  const [acting, setActing] = useState(false)
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

  function closeAction() {
    if (acting) return
    setAction(null)
  }

  async function handleConfirmAction() {
    if (token === null || id === undefined || action === null) return
    setActing(true)
    setActionError(null)
    try {
      if (action.kind === 'fulfil') {
        await marketApi.fulfilPurchase(token, id, action.purchase.id)
      } else {
        await marketApi.rejectPurchase(token, id, action.purchase.id)
      }
      setAction(null)
      retry()
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setActing(false)
    }
  }

  const history = (recent ?? []).filter((item) => item.status !== 'pending')

  return (
    <main className="page">
      <PageHeader
        title={`Заявки${pending !== null ? ` (${pending.length})` : ''}`}
        institutionName={institution?.name}
      />

      {pendingError !== null && <ScreenState state="error" error={pendingError} onRetry={retry} />}

      {pendingError === null && pending === null && <ScreenState state="loading" />}

      {pendingError === null && pending !== null && pending.length === 0 && (
        <ScreenState state="empty" message="Новых заявок нет" />
      )}

      {pendingError === null && pending !== null && pending.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Привилегия</th>
                <th scope="col">Ученик</th>
                <th scope="col">Подана</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {pending.map((item) => (
                <tr key={item.id}>
                  <td>
                    <p className="institution-name">{item.title}</p>
                    <p className="institution-meta">
                      <Money amount={item.price} />
                    </p>
                  </td>
                  <td>{item.user_name ?? 'Без имени'}</td>
                  <td>{new Date(item.created_at).toLocaleString('ru-RU')}</td>
                  <td>
                    <div className="table-actions">
                      <button
                        type="button"
                        onClick={() => setAction({ purchase: item, kind: 'fulfil' })}
                        disabled={acting}
                      >
                        Выдать
                      </button>
                      <button
                        type="button"
                        className="danger"
                        onClick={() => setAction({ purchase: item, kind: 'reject' })}
                        disabled={acting}
                      >
                        Отклонить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>История</h2>

      {recentError !== null && <ScreenState state="error" error={recentError} onRetry={retry} />}

      {recentError === null && recent === null && <ScreenState state="loading" />}

      {recentError === null && recent !== null && history.length === 0 && (
        <ScreenState state="empty" message="Решённых покупок пока нет" />
      )}

      {history.length > 0 && (
        <ul className="institution-list">
          {history.map((item) => (
            <li key={item.id} className="institution-item">
              <div>
                <p className="institution-name">
                  {item.title} — <Money amount={item.price} />
                </p>
                <p className="institution-meta">
                  {item.user_name ?? 'Без имени'} · {PURCHASE_STATUS_LABELS[item.status]}
                  {item.resolved_at !== null &&
                    ` · ${new Date(item.resolved_at).toLocaleString('ru-RU')}`}
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={action !== null}
        title={
          action?.kind === 'fulfil'
            ? `Выдать «${action.purchase.title}»?`
            : `Отклонить «${action?.purchase.title}»?`
        }
        description={
          action !== null ? (
            <>
              <p>
                {action.kind === 'fulfil'
                  ? 'Выдачу отменить нельзя.'
                  : 'Валюта вернётся ученику.'}
              </p>
              <FormError
                message={actionError === null ? undefined : messageForError(actionError)}
              />
            </>
          ) : undefined
        }
        confirmLabel={acting ? 'Сохраняем…' : action?.kind === 'fulfil' ? 'Выдать' : 'Отклонить'}
        danger={action?.kind === 'reject'}
        pending={acting}
        onConfirm={() => void handleConfirmAction()}
        onClose={closeAction}
      />
    </main>
  )
}
