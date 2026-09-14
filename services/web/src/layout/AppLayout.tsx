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
 * Адаптив и выезжающее меню для экранов уже 1024 px сюда не закладываются —
 * открытый вопрос В15.
 */
import { useState } from 'react'
import { Link, NavLink, Outlet, useNavigate } from 'react-router'

import { useAuth } from '../auth/authContext'
import { PixelSprite } from '../components/PixelSprite'
import { ROLE_LABELS } from '../i18n/labels'
import { getMenuEntries, isMenuGroup, type MenuLink } from '../navigation/menu'
import { usePendingPurchasesCount } from '../navigation/usePendingPurchasesCount'

function SidebarLink({ item, badge }: { item: MenuLink; badge?: number | null }) {
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      className={({ isActive }) => `sidebar-link${isActive ? ' sidebar-link-active' : ''}`}
    >
      <PixelSprite name={item.icon} size={16} />
      <span>{item.label}</span>
      {badge !== undefined && badge !== null && badge > 0 && (
        <span className="sidebar-badge">{badge}</span>
      )}
    </NavLink>
  )
}

function Sidebar() {
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
    <nav className="sidebar" aria-label="Основная навигация">
      <Link className="sidebar-brand" to="/">
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
                    />
                  </li>
                ))}
              </ul>
            </li>
          ) : (
            <li key={entry.key}>
              <SidebarLink item={entry} />
            </li>
          ),
        )}
      </ul>

      {institution !== null && (
        <div className="sidebar-footer">
          <p className="sidebar-institution">{institution.name}</p>
          <p className="sidebar-role">{ROLE_LABELS[institution.role]}</p>
          {user !== null && (
            <Link className="sidebar-email" to="/profile">
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

  if (institution === null) {
    return (
      <>
        <TopBar />
        <Outlet />
      </>
    )
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-content">
        <Outlet />
      </div>
    </div>
  )
}
