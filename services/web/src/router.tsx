/**
 * Карта адресов приложения.
 *
 * Доступ решается обёртками `RequireAuth` / `RequireAnon`, а не проверками
 * внутри страниц: nginx отдаёт `index.html` на любой URL.
 */
import { useCallback } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router'

import { AuthProvider } from './auth/AuthProvider'
import { RequireAnon } from './auth/RequireAnon'
import { RequireAuth } from './auth/RequireAuth'
import { RequireInstitution } from './auth/RequireInstitution'
import { AppLayout } from './layout/AppLayout'
import { ChangePasswordPage } from './pages/ChangePasswordPage'
import { CurrencyStudentsPage } from './pages/CurrencyStudentsPage'
import { GroupPage } from './pages/GroupPage'
import { GroupsPage } from './pages/GroupsPage'
import { HomePage } from './pages/HomePage'
import { InstitutionManagePage } from './pages/InstitutionManagePage'
import { InstitutionSettingsPage } from './pages/InstitutionSettingsPage'
import { InstitutionsPage } from './pages/InstitutionsPage'
import { InvitationsPage } from './pages/InvitationsPage'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { MarketPage } from './pages/MarketPage'
import { MyBalancePage } from './pages/MyBalancePage'
import { PrivilegesPage } from './pages/PrivilegesPage'
import { ProfilePage } from './pages/ProfilePage'
import { PurchasesPage } from './pages/PurchasesPage'
import { RegisterPage } from './pages/RegisterPage'
import { StudentCurrencyPage } from './pages/StudentCurrencyPage'
import { StudentsPage } from './pages/StudentsPage'
import { TeachersPage } from './pages/TeachersPage'

/**
 * Внутренняя оболочка: живёт уже внутри роутера, поэтому может отдать
 * провайдеру переход на выбор учреждения по коду `INSTITUTION_CONTEXT_REQUIRED`.
 */
function AppShell() {
  const navigate = useNavigate()
  const goToInstitutions = useCallback(() => {
    navigate('/institutions', { replace: true })
  }, [navigate])

  return (
    <AuthProvider onInstitutionContextRequired={goToInstitutions}>
      <Routes>
        <Route element={<RequireAnon />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route element={<AppLayout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/password" element={<ChangePasswordPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/institutions" element={<InstitutionsPage />} />
            <Route element={<RequireInstitution />}>
              <Route path="/institutions/:id/manage" element={<InstitutionManagePage />} />
              <Route path="/institutions/:id/invitations" element={<InvitationsPage />} />
              <Route path="/institutions/:id/teachers" element={<TeachersPage />} />
              <Route path="/institutions/:id/groups" element={<GroupsPage />} />
              <Route path="/institutions/:id/groups/:groupId" element={<GroupPage />} />
              <Route path="/institutions/:id/students" element={<StudentsPage />} />
              <Route path="/institutions/:id/settings" element={<InstitutionSettingsPage />} />
              <Route path="/institutions/:id/balance" element={<MyBalancePage />} />
              <Route path="/institutions/:id/currency" element={<CurrencyStudentsPage />} />
              <Route path="/institutions/:id/currency/:userId" element={<StudentCurrencyPage />} />
              <Route path="/institutions/:id/privileges" element={<PrivilegesPage />} />
              <Route path="/institutions/:id/market" element={<MarketPage />} />
              <Route path="/institutions/:id/purchases" element={<PurchasesPage />} />
            </Route>
            <Route path="/invite" element={<InvitePage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <AppShell />
    </BrowserRouter>
  )
}
