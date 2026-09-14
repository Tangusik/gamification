/**
 * Маркет — `/institutions/:id/market`, доступно только `student` (У1).
 * Баланс, активные позиции каталога, покупка и список своих покупок.
 *
 * Бэкенда маркета ещё нет — экран собран по контракту плана
 * `.claude/plans/07-market.md` (раздел Ч1), живых проверок не было.
 *
 * `operation_id` покупки создаётся на новую попытку и хранится в `useRef`,
 * пока не придёт окончательный ответ сервера (тот же приём, что у формы
 * начисления в `StudentCurrencyPage`, но per-позиция): при сетевом отказе
 * или таймауте (`ApiError(0, ...)`) повтор идёт с тем же id, при любом
 * ответе сервера — успехе или отказе с кодом — id сбрасывается и следующая
 * попытка получает новый. После `PRICE_CHANGED` каталог перечитывается
 * целиком (вместе с балансом и покупками) — минимальное решение вместо
 * точечной перезагрузки одной позиции.
 */
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount } from '../api/currency'
import { ApiError, NETWORK_ERROR } from '../api/errors'
import * as marketApi from '../api/market'
import type { Privilege, Purchase } from '../api/market'
import { useAuth } from '../auth/authContext'
import { FormError } from '../components/FormError'
import { messageForError } from '../i18n/errorMessages'
import { PURCHASE_STATUS_LABELS } from '../i18n/labels'
import { randomOperationId } from '../utils/uuid'

export function MarketPage() {
  const { id } = useParams<{ id: string }>()
  const { token } = useAuth()

  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [accountError, setAccountError] = useState<unknown>(null)

  const [privileges, setPrivileges] = useState<Privilege[] | null>(null)
  const [privilegesError, setPrivilegesError] = useState<unknown>(null)

  const [purchases, setPurchases] = useState<Purchase[] | null>(null)
  const [purchasesError, setPurchasesError] = useState<unknown>(null)

  const [refreshKey, setRefreshKey] = useState(0)

  const [buyingId, setBuyingId] = useState<string | null>(null)
  const [buyError, setBuyError] = useState<unknown>(null)
  const pendingOperation = useRef<{ privilegeId: string; operationId: string } | null>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    currencyApi
      .getMyCurrency(token, id)
      .then((loaded) => {
        if (!cancelled) setAccount(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setAccountError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, refreshKey])

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listPrivileges(token, id)
      .then((loaded) => {
        if (!cancelled) setPrivileges(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setPrivilegesError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, refreshKey])

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listMyPurchases(token, id)
      .then((loaded) => {
        if (!cancelled) setPurchases(loaded)
      })
      .catch((caught: unknown) => {
        if (!cancelled) setPurchasesError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, refreshKey])

  function retry() {
    setAccountError(null)
    setPrivilegesError(null)
    setPurchasesError(null)
    setRefreshKey((value) => value + 1)
  }

  async function handleBuy(privilege: Privilege) {
    if (token === null || id === undefined || buyingId !== null) return

    const pending = pendingOperation.current
    const operationId =
      pending !== null && pending.privilegeId === privilege.id
        ? pending.operationId
        : randomOperationId()
    pendingOperation.current = { privilegeId: privilege.id, operationId }

    setBuyingId(privilege.id)
    setBuyError(null)
    try {
      await marketApi.purchase(token, id, {
        operation_id: operationId,
        privilege_id: privilege.id,
        expected_price: privilege.price,
      })
      pendingOperation.current = null
      retry()
    } catch (caught) {
      // Сетевой отказ или таймаут — сервер решения не вынес, id сохраняется
      // для повтора. Любой другой ответ (в том числе `PRICE_CHANGED`) —
      // окончательный, следующая попытка получит новый id.
      const isNetworkFailure = caught instanceof ApiError && caught.code === NETWORK_ERROR
      if (!isNetworkFailure) {
        pendingOperation.current = null
      }
      if (caught instanceof ApiError && caught.code === 'PRICE_CHANGED') {
        retry()
      }
      setBuyError(caught)
    } finally {
      setBuyingId(null)
    }
  }

  return (
    <>
      <main className="page">
        <h1>Маркет</h1>

        {accountError !== null && <FormError message={messageForError(accountError)} />}
        {accountError === null && account !== null && (
          <p>
            Баланс: <strong>{account.balance}</strong>
          </p>
        )}

        {privilegesError !== null && (
          <>
            <FormError message={messageForError(privilegesError)} />
            <button type="button" onClick={retry}>
              Повторить
            </button>
          </>
        )}

        {privilegesError === null && privileges === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {privileges !== null && privileges.length === 0 && <p>Каталог пока пуст.</p>}

        {privileges !== null && privileges.length > 0 && (
          <ul className="institution-list">
            {privileges.map((privilege) => (
              <li key={privilege.id} className="institution-item">
                <div>
                  <p className="institution-name">
                    {privilege.title} — {privilege.price}
                  </p>
                  {privilege.description !== null && (
                    <p className="institution-meta">{privilege.description}</p>
                  )}
                  <p className="institution-meta">
                    {privilege.stock === null ? 'Без ограничения' : `Остаток: ${privilege.stock}`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void handleBuy(privilege)}
                  disabled={buyingId !== null || (privilege.stock !== null && privilege.stock <= 0)}
                >
                  {buyingId === privilege.id ? 'Покупаем…' : 'Купить'}
                </button>
              </li>
            ))}
          </ul>
        )}

        {buyError !== null && <FormError message={messageForError(buyError)} />}

        <h2>Мои покупки</h2>

        {purchasesError !== null && <FormError message={messageForError(purchasesError)} />}

        {purchasesError === null && purchases === null && (
          <p className="page-status" role="status">
            Загрузка…
          </p>
        )}

        {purchases !== null && purchases.length === 0 && <p>Покупок пока нет.</p>}

        {purchases !== null && purchases.length > 0 && (
          <ul className="institution-list">
            {purchases.map((item) => (
              <li key={item.id} className="institution-item">
                <div>
                  <p className="institution-name">
                    {item.title} — {item.price}
                  </p>
                  <p className="institution-meta">
                    {PURCHASE_STATUS_LABELS[item.status]} ·{' '}
                    {new Date(item.created_at).toLocaleString()}
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
