/**
 * Счётчик заявок `pending` у пункта «Маркет → Заявки» в меню администратора
 * (раздел 3 и раздел 7 плана `08-web-ux-and-deploy.md`).
 *
 * Источник — `listPurchases(..., { status: 'pending' })`. Обновляется при
 * смене маршрута и при возврате фокуса во вкладку (`visibilitychange`/
 * `focus`), опроса по таймеру нет. При ошибке счётчик просто не
 * показывается (`null`).
 */
import { useCallback, useEffect, useState } from 'react'
import { useLocation } from 'react-router'

import * as marketApi from '../api/market'

export function usePendingPurchasesCount(
  token: string | null,
  institutionId: string | null,
  enabled: boolean,
): number | null {
  const [count, setCount] = useState<number | null>(null)
  const { pathname } = useLocation()

  const canFetch = enabled && token !== null && institutionId !== null

  /** Отдельная функция для обработчиков фокуса — сам эффект её не вызывает напрямую. */
  const refetch = useCallback(() => {
    if (!canFetch) return
    marketApi
      .listPurchases(token as string, institutionId as string, { status: 'pending' })
      .then((loaded) => setCount(loaded.length))
      .catch(() => setCount(null))
  }, [canFetch, token, institutionId])

  // Смена маршрута: перечитываем счётчик тем же запросом, что и при монтировании.
  // Пока не готов первый запрос по включённому состоянию, эффект ничего не
  // делает — счётчик, если не готов к показу, скрывает уже возврат ниже.
  useEffect(() => {
    if (!canFetch) return

    let cancelled = false
    marketApi
      .listPurchases(token as string, institutionId as string, { status: 'pending' })
      .then((loaded) => {
        if (!cancelled) setCount(loaded.length)
      })
      .catch(() => {
        if (!cancelled) setCount(null)
      })
    return () => {
      cancelled = true
    }
  }, [canFetch, token, institutionId, pathname])

  // Возврат фокуса во вкладку — опроса по таймеру нет.
  useEffect(() => {
    function onFocusLike() {
      if (document.visibilityState === 'visible') refetch()
    }
    window.addEventListener('focus', onFocusLike)
    document.addEventListener('visibilitychange', onFocusLike)
    return () => {
      window.removeEventListener('focus', onFocusLike)
      document.removeEventListener('visibilitychange', onFocusLike)
    }
  }, [refetch])

  // Пока `canFetch` не выполнено (не тот институт/роль или ещё нет токена),
  // отдаём `null` напрямую, без промежуточного `setState` в эффекте: значение
  // производится из текущих пропов, а не хранится как отдельное состояние.
  return canFetch ? count : null
}
