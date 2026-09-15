/**
 * Название внутренней валюты текущего учреждения (В5/б, ответ закрыт
 * 2026-09-14 — `.claude/plans/08-web-ux-and-deploy.md`).
 *
 * `institution.currencyName` приходит из `GET /institutions` и может быть
 * `null`, пока учреждение не задало его в настройках
 * (`InstitutionSettingsPage`). Запасное слово — «валюта», уже используемое
 * в текстах фронта («Начислить валюту», «Начисление валюты»), а не
 * нейтральное «монеты»: второе не встречается в интерфейсе и добавило бы
 * второе слово для одного понятия.
 *
 * Вне контекста учреждения (`institution === null`) тоже возвращает
 * запасное слово — страница, откуда хук вызван без контекста, сама решает,
 * показывать ли его.
 */
import { useAuth } from './authContext'

const FALLBACK_CURRENCY_NAME = 'валюта'

export function useCurrencyName(): string {
  const { institution } = useAuth()
  return institution?.currencyName ?? FALLBACK_CURRENCY_NAME
}
