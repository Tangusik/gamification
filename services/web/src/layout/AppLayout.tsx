/**
 * Layout-маршрут авторизованной части — раздел 3 плана `08-web-ux-and-deploy.md`
 * (ответы В2/В4), этап 08a/A2.
 *
 * Учреждение выбрано (`useAuth().institution`) → закреплённое меню слева по
 * таблице ролей (`navigation/menu.ts`). Учреждения нет (онбординг, `/password`,
 * `/invite`, `/profile` без контекста) → минимальная верхняя полоса: бренд,
 * «Профиль», «Выход».
 *
 * Страницы сами рендерят свой `<main>` — здесь его нет намеренно, чтобы не
 * задваивать landmark.
 *
 * Адаптив (В15/а, ответ закрыт): при ширине <1024 px меню слева превращается
 * в верхнюю полосу с кнопкой «Меню» и выезжающую панель — правила ниже и в
 * `src/index.css`, блок «Адаптив меню (В15)». `TopBar` (учреждения нет)
 * адаптива не требует: полоса и так одна строка с `flex-wrap`.
 */
import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'

import { useAuth } from '../auth/authContext'
import { PixelSprite } from '../components/PixelSprite'
import { ROLE_LABELS } from '../i18n/labels'
import { getMenuEntries, isMenuGroup, type MenuLink } from '../navigation/menu'
import { usePendingPurchasesCount } from '../navigation/usePendingPurchasesCount'

function SidebarLink({
  item,
  badge,
  onNavigate,
}: {
  item: MenuLink
  badge?: number | null
  onNavigate: () => void
}) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) => `sidebar-link${isActive ? ' sidebar-link-active' : ''}`}
      onClick={onNavigate}
    >
      <PixelSprite name={item.icon} size={16} />
      <span>{item.label}</span>
      {badge !== undefined && badge !== null && badge > 0 && (
        <span className="sidebar-badge">{badge}</span>
      )}
    </NavLink>
  )
}

type SidebarProps = {
  panelId: string
  open: boolean
  /** Переход по пункту закрывает выезжающую панель на узком экране (В15). */
  onNavigate: () => void
}

function Sidebar({ panelId, open, onNavigate }: SidebarProps) {
  const { user, institution, token, logout } = useAuth()
  const navigate = useNavigate()
  const [pending, setPending] = useState(false)

  // Компонент рендерится только когда `institution !== null` (см. AppLayout).
  const entries = institution === null ? [] : getMenuEntries(institution.role, institution.id)
  const pendingCount = usePendingPurchasesCount(
    token,
    institution?.id ?? null,
    institution?.role === 'institution_admin',
  )

  async function handleLogout() {
    setPending(true)
    try {
      // Выход из `AuthContext` безусловен и не бросает — ошибок здесь не ловим.
      await logout()
    } finally {
      setPending(false)
      navigate('/login', { replace: true })
    }
  }

  return (
    <nav
      id={panelId}
      className={`sidebar${open ? ' sidebar-open' : ''}`}
      aria-label="Основная навигация"
    >
      <Link className="sidebar-brand" to="/" onClick={onNavigate}>
        Геймификация
      </Link>

      <ul className="sidebar-menu">
        {entries.map((entry) =>
          isMenuGroup(entry) ? (
            <li key={entry.key} className="sidebar-group">
              <p className="sidebar-group-label">
                <PixelSprite name={entry.icon} size={14} />
                <span>{entry.label}</span>
              </p>
              <ul className="sidebar-submenu">
                {entry.children.map((child) => (
                  <li key={child.key}>
                    <SidebarLink
                      item={child}
                      badge={child.key === 'market-purchases' ? pendingCount : undefined}
                      onNavigate={onNavigate}
                    />
                  </li>
                ))}
              </ul>
            </li>
          ) : (
            <li key={entry.key}>
              <SidebarLink item={entry} onNavigate={onNavigate} />
            </li>
          ),
        )}
      </ul>

      {institution !== null && (
        <div className="sidebar-footer">
          <p className="sidebar-institution">{institution.name}</p>
          <p className="sidebar-role">{ROLE_LABELS[institution.role]}</p>
          {user !== null && (
            <Link className="sidebar-email" to="/profile" onClick={onNavigate}>
              {user.email}
            </Link>
          )}
          <button type="button" onClick={() => void handleLogout()} disabled={pending}>
            {pending ? 'Выходим…' : 'Выход'}
          </button>
        </div>
      )}
    </nav>
  )
}

function TopBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [pending, setPending] = useState(false)

  async function handleLogout() {
    setPending(true)
    try {
      await logout()
    } finally {
      setPending(false)
      navigate('/login', { replace: true })
    }
  }

  return (
    <header className="topbar">
      <Link className="topbar-brand" to="/">
        Геймификация
      </Link>
      <nav className="topbar-nav" aria-label="Основная навигация">
        <Link to="/profile">Профиль</Link>
        {user !== null && <span className="topbar-user">{user.email}</span>}
        <button type="button" onClick={() => void handleLogout()} disabled={pending}>
          {pending ? 'Выходим…' : 'Выход'}
        </button>
      </nav>
    </header>
  )
}

export function AppLayout() {
  const { institution } = useAuth()
  const panelId = useId()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const location = useLocation()
  const [trackedPathname, setTrackedPathname] = useState(location.pathname)

  /**
   * Закрыть панель. `returnFocus` — вернуть фокус на кнопку «Меню»: так для
   * Esc и клика по подложке (фокус в этот момент внутри панели или на
   * подложке), но не для перехода по пункту — там фокус и так уходит на
   * новую страницу вместе с навигацией, оттягивать его назад на кнопку
   * не нужно.
   */
  const closeMenu = useCallback((returnFocus: boolean) => {
    setMenuOpen(false)
    if (returnFocus) menuButtonRef.current?.focus()
  }, [])

  // Esc закрывает панель, пока она открыта.
  useEffect(() => {
    if (!menuOpen) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') closeMenu(true)
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [menuOpen, closeMenu])

  // Смена маршрута другим способом (например, кнопкой браузера «Назад»)
  // тоже закрывает панель — без этого она осталась бы открытой поверх новой
  // страницы на узком экране. Правка состояния прямо при рендере (а не в
  // `useEffect`) — рекомендованный React-приём для «подгонки состояния под
  // проп/внешнее значение», без лишнего цикла рендера от эффекта.
  if (location.pathname !== trackedPathname) {
    setTrackedPathname(location.pathname)
    setMenuOpen(false)
  }

  if (institution === null) {
    return (
      <>
        <TopBar />
        <Outlet />
      </>
    )
  }

  return (
    <>
      {/* Верхняя полоса с кнопкой меню — видна только <1024 px (В15/а). */}
      <div className="mobile-topbar">
        <Link className="mobile-topbar-brand" to="/">
          Геймификация
        </Link>
        <button
          type="button"
          ref={menuButtonRef}
          className="menu-toggle"
          aria-expanded={menuOpen}
          aria-controls={panelId}
          onClick={() => setMenuOpen((value) => !value)}
        >
          <span className="menu-toggle-icon" aria-hidden="true" />
          <span>Меню</span>
        </button>
      </div>

      <div className="app-shell">
        {menuOpen && (
          // Подложка существует только пока панель открыта; на ≥1024 px
          // панель и так не выезжает (см. index.css), клика по ней не будет.
          <div className="sidebar-backdrop" onClick={() => closeMenu(true)} aria-hidden="true" />
        )}
        <Sidebar panelId={panelId} open={menuOpen} onNavigate={() => closeMenu(false)} />
        <div className="app-content">
          <Outlet />
        </div>
      </div>
    </>
  )
}
