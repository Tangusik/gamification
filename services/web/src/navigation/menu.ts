/**
 * Состав меню слева по ролям — один массив «роль → пункты» в одном файле,
 * раздел 3 плана `.claude/plans/08-web-ux-and-deploy.md` (ответ В4).
 *
 * Меню только скрывает недоступное, защита остаётся на бэкенде
 * (403 `INSUFFICIENT_ROLE`).
 */
import type { UserRole } from '../api/auth'
import type { SpriteName } from '../components/PixelSprite'

export type MenuLink = {
  key: string
  label: string
  to: string
  icon: SpriteName
}

export type MenuGroup = {
  key: string
  label: string
  icon: SpriteName
  children: MenuLink[]
}

export type MenuEntry = MenuLink | MenuGroup

export function isMenuGroup(entry: MenuEntry): entry is MenuGroup {
  return 'children' in entry
}

/**
 * Пункты меню для роли в контексте учреждения `institutionId`.
 *
 * «Ученики» ведёт на `…/currency` — временно, до объединения экранов
 * в 08b (карточка ученика с балансом и начислением). Ссылка «Управление
 * учениками» на `…/students` для admin живёт на `CurrencyStudentsPage`.
 */
export function getMenuEntries(role: UserRole, institutionId: string): MenuEntry[] {
  const path = (suffix: string) => `/institutions/${institutionId}${suffix}`

  switch (role) {
    case 'institution_admin':
      return [
        { key: 'home', label: 'Главная', to: '/', icon: 'house' },
        { key: 'students', label: 'Ученики', to: path('/currency'), icon: 'user' },
        { key: 'teachers', label: 'Преподаватели', to: path('/teachers'), icon: 'star' },
        { key: 'groups', label: 'Группы', to: path('/groups'), icon: 'chest' },
        { key: 'invitations', label: 'Приглашения', to: path('/invitations'), icon: 'qr' },
        {
          key: 'market',
          label: 'Маркет',
          icon: 'coin',
          children: [
            { key: 'market-catalog', label: 'Каталог', to: path('/privileges'), icon: 'coin' },
            { key: 'market-purchases', label: 'Заявки', to: path('/purchases'), icon: 'check' },
          ],
        },
        { key: 'settings', label: 'Настройки учреждения', to: path('/settings'), icon: 'bolt' },
      ]
    case 'teacher':
      return [
        { key: 'home', label: 'Главная', to: '/', icon: 'house' },
        { key: 'students', label: 'Ученики', to: path('/currency'), icon: 'user' },
        { key: 'groups', label: 'Группы', to: path('/groups'), icon: 'chest' },
        { key: 'invitations', label: 'Приглашения', to: path('/invitations'), icon: 'qr' },
        // Пункта «Маркет» у teacher нет — открытый вопрос В14. Добавить его
        // назад — правка одной строки здесь.
      ]
    case 'student':
      return [
        { key: 'home', label: 'Главная', to: '/', icon: 'house' },
        { key: 'market', label: 'Маркет', to: path('/market'), icon: 'coin' },
        { key: 'balance', label: 'История операций', to: path('/balance'), icon: 'bolt' },
      ]
  }
}
