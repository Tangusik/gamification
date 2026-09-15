/**
 * Каталог привилегий — `/institutions/:id/privileges`. Управляет только
 * `institution_admin` (П2): создание позиций, правка цены, остатка (в том
 * числе очистка до «без ограничения», L2) и активности. Скрытие позиции —
 * снятие `is_active` — действие обратимое, подтверждения не требует
 * (раздел 7 плана `08-web-ux-and-deploy.md`).
 *
 * Строка остатка пустая = «без ограничения» (`stock: null`). Правка отправляет
 * только изменившиеся поля: очистка остатка шлёт `stock: null` явно, а поля,
 * которые админ не трогал, в тело `PATCH` вовсе не попадают (У11) — это же
 * гарантирует TypeScript-тип `UpdatePrivilegeInput`.
 */
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useParams } from 'react-router'

import { ApiError } from '../api/errors'
import * as marketApi from '../api/market'
import type { Privilege, UpdatePrivilegeInput } from '../api/market'
import { useAuth } from '../auth/authContext'
import { useCurrencyName } from '../auth/useCurrencyName'
import { FieldError } from '../components/FieldError'
import { FormError } from '../components/FormError'
import { PageHeader } from '../components/PageHeader'
import { ScreenState } from '../components/ScreenState'
import { messageForError } from '../i18n/errorMessages'

type PrivilegeEdit = {
  price: string
  stock: string
  is_active: boolean
}

function toEdit(privilege: Privilege): PrivilegeEdit {
  return {
    price: String(privilege.price),
    stock: privilege.stock === null ? '' : String(privilege.stock),
    is_active: privilege.is_active,
  }
}

export function PrivilegesPage() {
  const { id } = useParams<{ id: string }>()
  const { token, institution } = useAuth()
  const currencyName = useCurrencyName()

  const [items, setItems] = useState<Privilege[] | null>(null)
  const [loadError, setLoadError] = useState<unknown>(null)
  const [attempt, setAttempt] = useState(0)

  const [edits, setEdits] = useState<Record<string, PrivilegeEdit>>({})
  const [savingId, setSavingId] = useState<string | null>(null)
  const [saveError, setSaveError] = useState<unknown>(null)

  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [price, setPrice] = useState('')
  const [stock, setStock] = useState('')
  const [isActive, setIsActive] = useState(true)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<ApiError | null>(null)
  const titleInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (token === null || id === undefined) return
    let cancelled = false
    marketApi
      .listPrivileges(token, id)
      .then((loaded) => {
        if (cancelled) return
        setItems(loaded)
        setEdits(Object.fromEntries(loaded.map((item) => [item.id, toEdit(item)])))
      })
      .catch((caught: unknown) => {
        if (!cancelled) setLoadError(caught)
      })
    return () => {
      cancelled = true
    }
  }, [token, id, attempt])

  function retry() {
    setItems(null)
    setLoadError(null)
    setAttempt((value) => value + 1)
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (token === null || id === undefined) return
    setCreating(true)
    setCreateError(null)
    try {
      await marketApi.createPrivilege(token, id, {
        title,
        description: description.trim() === '' ? null : description,
        price: Number(price),
        stock: stock.trim() === '' ? undefined : Number(stock),
        is_active: isActive,
      })
      setTitle('')
      setDescription('')
      setPrice('')
      setStock('')
      setIsActive(true)
      retry()
    } catch (caught) {
      setCreateError(caught instanceof ApiError ? caught : new ApiError(0, 'UNKNOWN_ERROR'))
    } finally {
      setCreating(false)
    }
  }

  function updateEdit(privilegeId: string, patch: Partial<PrivilegeEdit>) {
    setEdits((prev) => ({ ...prev, [privilegeId]: { ...prev[privilegeId], ...patch } }))
  }

  async function handleSave(privilege: Privilege) {
    if (token === null || id === undefined) return
    const edit = edits[privilege.id]
    if (edit === undefined) return

    const patch: UpdatePrivilegeInput = {}
    const editedPrice = Number(edit.price)
    if (editedPrice !== privilege.price) patch.price = editedPrice
    const editedStock = edit.stock.trim() === '' ? null : Number(edit.stock)
    if (editedStock !== privilege.stock) patch.stock = editedStock
    if (edit.is_active !== privilege.is_active) patch.is_active = edit.is_active
    if (Object.keys(patch).length === 0) return

    setSavingId(privilege.id)
    setSaveError(null)
    try {
      const updated = await marketApi.updatePrivilege(token, id, privilege.id, patch)
      setItems((prev) => prev?.map((item) => (item.id === updated.id ? updated : item)) ?? prev)
      setEdits((prev) => ({ ...prev, [updated.id]: toEdit(updated) }))
    } catch (caught) {
      setSaveError(caught)
    } finally {
      setSavingId(null)
    }
  }

  const createFieldErrors = createError?.fieldErrors

  return (
    <main className="page">
      <PageHeader title="Каталог привилегий" institutionName={institution?.name} />

      <form className="form" onSubmit={handleCreate} noValidate>
        <div className="field">
          <label htmlFor="privilege-title">Название</label>
          <input
            ref={titleInputRef}
            id="privilege-title"
            name="title"
            type="text"
            required
            maxLength={100}
            value={title}
            onChange={(event) => setTitle(event.target.value)}
            disabled={creating}
            aria-invalid={createFieldErrors?.title !== undefined}
          />
          <FieldError message={createFieldErrors?.title} />
        </div>

        <div className="field">
          <label htmlFor="privilege-description">Описание (необязательно)</label>
          <input
            id="privilege-description"
            name="description"
            type="text"
            maxLength={500}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            disabled={creating}
            aria-invalid={createFieldErrors?.description !== undefined}
          />
          <FieldError message={createFieldErrors?.description} />
        </div>

        <div className="field">
          <label htmlFor="privilege-price">{`Цена (в «${currencyName}»)`}</label>
          <input
            id="privilege-price"
            name="price"
            type="number"
            min={1}
            max={100000}
            required
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            disabled={creating}
            aria-invalid={createFieldErrors?.price !== undefined}
          />
          <FieldError message={createFieldErrors?.price} />
        </div>

        <div className="field">
          <label htmlFor="privilege-stock">Остаток (пусто — без ограничения)</label>
          <input
            id="privilege-stock"
            name="stock"
            type="number"
            min={0}
            value={stock}
            onChange={(event) => setStock(event.target.value)}
            disabled={creating}
            aria-invalid={createFieldErrors?.stock !== undefined}
          />
          <FieldError message={createFieldErrors?.stock} />
        </div>

        <div className="field">
          <label htmlFor="privilege-active">
            <input
              id="privilege-active"
              name="is_active"
              type="checkbox"
              checked={isActive}
              onChange={(event) => setIsActive(event.target.checked)}
              disabled={creating}
            />{' '}
            Активна
          </label>
        </div>

        <FormError message={createError === null ? undefined : messageForError(createError)} />

        <button type="submit" disabled={creating}>
          {creating ? 'Создаём…' : 'Добавить позицию'}
        </button>
      </form>

      {loadError !== null && <ScreenState state="error" error={loadError} onRetry={retry} />}

      {loadError === null && items === null && <ScreenState state="loading" />}

      {loadError === null && items !== null && items.length === 0 && (
        <ScreenState
          state="empty"
          message="Позиций пока нет"
          action={
            <button type="button" onClick={() => titleInputRef.current?.focus()}>
              Добавить первую привилегию
            </button>
          }
        />
      )}

      {loadError === null && items !== null && items.length > 0 && (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th scope="col">Название</th>
                <th scope="col">Цена</th>
                <th scope="col">Остаток</th>
                <th scope="col">Активна</th>
                <th scope="col" />
              </tr>
            </thead>
            <tbody>
              {items.map((privilege) => {
                const edit = edits[privilege.id] ?? toEdit(privilege)
                const busy = savingId === privilege.id
                return (
                  <tr key={privilege.id}>
                    <td>
                      <p className="institution-name">{privilege.title}</p>
                      {privilege.description !== null && (
                        <p className="institution-meta">{privilege.description}</p>
                      )}
                    </td>
                    <td>
                      <label className="sr-only" htmlFor={`privilege-price-${privilege.id}`}>
                        Цена
                      </label>
                      <input
                        id={`privilege-price-${privilege.id}`}
                        type="number"
                        min={1}
                        max={100000}
                        value={edit.price}
                        onChange={(event) =>
                          updateEdit(privilege.id, { price: event.target.value })
                        }
                        disabled={savingId !== null}
                      />
                    </td>
                    <td>
                      <label className="sr-only" htmlFor={`privilege-stock-${privilege.id}`}>
                        Остаток
                      </label>
                      <input
                        id={`privilege-stock-${privilege.id}`}
                        type="number"
                        min={0}
                        placeholder="без ограничения"
                        value={edit.stock}
                        onChange={(event) =>
                          updateEdit(privilege.id, { stock: event.target.value })
                        }
                        disabled={savingId !== null}
                      />
                    </td>
                    <td>
                      <label className="sr-only" htmlFor={`privilege-active-${privilege.id}`}>
                        Активна
                      </label>
                      <input
                        id={`privilege-active-${privilege.id}`}
                        type="checkbox"
                        checked={edit.is_active}
                        onChange={(event) =>
                          updateEdit(privilege.id, { is_active: event.target.checked })
                        }
                        disabled={savingId !== null}
                      />
                    </td>
                    <td>
                      <button
                        type="button"
                        onClick={() => void handleSave(privilege)}
                        disabled={savingId !== null}
                      >
                        {busy ? 'Сохраняем…' : 'Сохранить'}
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {saveError !== null && <FormError message={messageForError(saveError)} />}
    </main>
  )
}
