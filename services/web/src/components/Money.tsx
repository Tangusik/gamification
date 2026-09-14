/**
 * Сумма валюты со спрайтом монеты, разбиением разрядов по `ru-RU`
 * («1 240») и знаком «−» на списании (раздел 7 плана
 * `08-web-ux-and-deploy.md`).
 *
 * Название валюты — открытый вопрос В5, поэтому компонент его не выводит и
 * не вводит собственное слово.
 */
import { PixelSprite } from './PixelSprite'

type Props = {
  amount: number
  /** Показать «+» перед положительной суммой (начисления в ленте операций). Отрицательная сумма всегда со знаком «−». */
  showPlus?: boolean
  size?: number
}

export function Money({ amount, showPlus = false, size = 16 }: Props) {
  const isNegative = amount < 0
  const formatted = Math.abs(amount).toLocaleString('ru-RU')
  const sign = isNegative ? '−' : showPlus ? '+' : ''

  return (
    <span className={isNegative ? 'money money-negative' : 'money'}>
      <PixelSprite name="coin" size={size} />
      {sign}
      {formatted}
    </span>
  )
}
