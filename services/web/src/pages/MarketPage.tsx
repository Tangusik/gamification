/**
 * Маркет — `/institutions/:id/market`.
 *
 * `student` — баланс, покупка с подтверждением и список своих покупок.
 * `teacher` (В14/б) — только каталог на чтение: без баланса, без покупки и
 * без «моих покупок» — ни один из связанных вызовов (`GET /me/currency`,
 * `GET /me/purchases`, `POST /purchases`) для этой роли не делается.
 * `GET /privileges` открыт обеим ролям (`ListPrivileges`,
 * `CATALOGUE_VIEW_ROLES` — `app/business/use_cases/market.py`), учителю
 * сервер отдаёт только активные позиции.
 *
 * `operation_id` покупки создаётся на новую попытку и хранится в `useRef` до
 * окончательного ответа сервера — политика зафиксирована в
 * `web-service/01-structure.md` («Маркет привилегий»), здесь не меняется:
 * id сбрасывается только при успехе и при `PRICE_CHANGED` (каталог
 * перечитывается, следующая попытка уходит с новым id). При любом другом
 * отказе — `NETWORK_ERROR`, 5xx, `OUT_OF_STOCK`, `INSUFFICIENT_BALANCE`,
 * `UNKNOWN_ERROR` и т. п. — сервер мог уже закоммитить покупку, поэтому id
 * не меняется, чтобы повтор той же кнопкой не привёл к двойному списанию.
 */
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router'

import * as currencyApi from '../api/currency'
import type { CurrencyAccount } from '../api/currency'
import { ApiError } from '../api/errors'
import * as marketApi from '../api/market'
import type { Privilege, Purchase } from '../api/market'
import { useAuth } from '../auth/authContext'
import { useCurrencyName } from '../auth/useCurrencyName'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { FormError } from '../components/FormError'
import { Money } from '../components/Money'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'
import { PURCHASE_STATUS_LABELS } from '../i18n/labels'
import { randomOperationId } from '../utils/uuid'

export function MarketPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const currencyName = useCurrencyName()

  const isStudent = institution?.role === 'student'

  const [account, setAccount] = useState<CurrencyAccount | null>(null)
  const [accountError, setAccountError] = useState<unknown>(null)

  const [privileges, setPrivileges] = useState<Privilege[] | null>(null)
  const [privilegesError, setPrivilegesError] = useState<unknown>(null)

  const [purchases, setPurchases] = useState<Purchase[] | null>(null)
  const [purchasesError, setPurchasesError] = useState<unknown>(null)

  const [refreshKey, setRefreshKey] = useState(0)

  const [selected, setSelected] = useState<Privilege | null>(null)
  const [buying, setBuying] = useState(false)
  const [buyError, setBuyError] = useState<unknown>(null)
  const pendingOperation = useRef<{ privilegeId: string; operationId: string } | null>(null)

  // Баланс — только у ученика: у преподавателя эндпоинт `/me/currency`
  // рассчитан на роль `student` и ответит `INSUFFICIENT_ROLE`.
  useEffect(() => {
    if (!isStudent || token === null || id === undefined) return
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
  }, [isStudent, token, id, refreshKey])

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

  // Свои покупки — тоже только у ученика.
  useEffect(() => {
    if (!isStudent || token === null || id === undefined) return
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
  }, [isStudent, token, id, refreshKey])

  function retry() {
    setAccountError(null)
    setPrivilegesError(null)
    setPurchasesError(null)
    setRefreshKey((value) => value + 1)
  }

  function openConfirm(privilege: Privilege) {
    setBuyError(null)
    setSelected(privilege)
  }

  function closeConfirm() {
    if (buying) return
    setSelected(null)
  }

  async function handleConfirmBuy() {
    const privilege = selected
    if (token === null || id === undefined || privilege === null) return

    const pending = pendingOperation.current
    const operationId =
      pending !== null && pending.privilegeId === privilege.id
        ? pending.operationId
        : randomOperationId()
    pendingOperation.current = { privilegeId: privilege.id, operationId }

    setBuying(true)
    setBuyError(null)
    try {
      await marketApi.purchase(token, id, {
        operation_id: operationId,
        privilege_id: privilege.id,
        expected_price: privilege.price,
      })
      pendingOperation.current = null
      setSelected(null)
      retry()
    } catch (caught) {
      // id сбрасывается только при `PRICE_CHANGED` — каталог перечитывается,
      // и следующая попытка обязана уйти с новым id. Во всех остальных
      // случаях (`NETWORK_ERROR`, 5xx, `OUT_OF_STOCK`, `INSUFFICIENT_BALANCE`,
      // `UNKNOWN_ERROR` и т. п.) сервер мог уже закоммитить покупку — id
      // сохраняется, чтобы повтор той же кнопкой не привёл к двойному списанию.
      if (caught instanceof ApiError && caught.code === 'PRICE_CHANGED') {
        pendingOperation.current = null
        retry()
        setSelected(null)
      }
      setBuyError(caught)
    } finally {
      setBuying(false)
    }
  }

  const loadError = privilegesError ?? (isStudent ? accountError : null)

  return (
    <main className="page">
      <PageHeader title="Маркет" institutionName={institution?.name} />

      {isStudent && loadError === null && account !== null && (
        <p className="market-balance">
          Баланс: <Money amount={account.balance} size={20} /> {currencyName}
        </p>
      )}

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}

      {loadError === null && privileges === null && <ScreenState state="loading" />}

      {loadError === null && privileges !== null && privileges.length === 0 && (
        <ScreenState state="empty" message="Учреждение ещё не добавило привилегии" />
      )}

      {loadError === null && privileges !== null && privileges.length > 0 && (
        <ul className="market-grid">
          {privileges.map((privilege) => {
            const outOfStock = privilege.stock !== null && privilege.stock <= 0
            const shortage =
              isStudent && account !== null ? privilege.price - account.balance : 0
            const cannotAfford = isStudent && account !== null && shortage > 0

            let buyLabel = 'Купить'
            if (outOfStock) buyLabel = 'Нет в наличии'
            else if (cannotAfford) buyLabel = `Не хватает ${shortage}`

            return (
              <li key={privilege.id} className="market-card">
                <div>
                  <p className="institution-name">{privilege.title}</p>
                  {privilege.description !== null && (
                    <p className="institution-meta">{privilege.description}</p>
                  )}
                  <p className="market-price">
                    <Money amount={privilege.price} /> {currencyName}
                  </p>
                  <p className="institution-meta">
                    {privilege.stock === null ? 'Без ограничения' : `Остаток: ${privilege.stock}`}
                  </p>
                </div>
                {isStudent && (
                  <button
                    type="button"
                    onClick={() => openConfirm(privilege)}
                    disabled={outOfStock || cannotAfford}
                  >
                    {buyLabel}
                  </button>
                )}
              </li>
            )
          })}
        </ul>
      )}

      {isStudent && (
        <>
          <h2>Мои покупки</h2>

          {purchasesError !== null && (
            <ScreenState state="error" error={purchasesError} onRetry={retry} />
          )}

          {purchasesError === null && purchases === null && <ScreenState state="loading" />}

          {purchasesError === null && purchases !== null && purchases.length === 0 && (
            <ScreenState state="empty" message="Покупок пока нет" />
          )}

          {purchasesError === null && purchases !== null && purchases.length > 0 && (
            <ul className="institution-list">
              {purchases.map((item) => (
                <li key={item.id} className="institution-item">
                  <div>
                    <p className="institution-name">
                      {item.title} — <Money amount={item.price} />
                    </p>
                    <p className="institution-meta">
                      {PURCHASE_STATUS_LABELS[item.status]} ·{' '}
                      {new Date(item.created_at).toLocaleString('ru-RU')}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <ConfirmDialog
            open={selected !== null}
            title={selected !== null ? `Купить «${selected.title}»?` : ''}
            description={
              selected !== null && account !== null ? (
                <>
                  <p>
                    Цена: <Money amount={selected.price} /> {currencyName}
                  </p>
                  <p>
                    Остаток после покупки: <Money amount={account.balance - selected.price} />{' '}
                    {currencyName}
                  </p>
                  <FormError message={buyError === null ? undefined : messageForError(buyError)} />
                </>
              ) : undefined
            }
            confirmLabel={buying ? 'Покупаем…' : 'Купить'}
            pending={buying}
            onConfirm={() => void handleConfirmBuy()}
            onClose={closeConfirm}
          />
        </>
      )}
    </main>
  )
}
