/**
 * Уведомление об успехе — показывается на месте, без ухода со страницы
 * (раздел 7 плана `08-web-ux-and-deploy.md`). Видимостью и временем жизни
 * управляет страница, компонент только рисует состояние.
 */
import { PixelSprite } from './PixelSprite'

type Props = {
  show: boolean
  text?: string
}

export function SavedNotice({ show, text = 'Сохранено' }: Props) {
  if (!show) return null
  return (
    <p className="saved-notice" role="status">
      <PixelSprite name="check" size={14} />
      {text}
    </p>
  )
}
