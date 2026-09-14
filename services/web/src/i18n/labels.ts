/**
 * Человеческие подписи для перечислений gamification.
 *
 * Вынесены отдельно, потому что нужны сразу трём экранам (`InstitutionsPage`,
 * `InvitationsPage`, `InvitePage`) — дублировать карты по месту не стоило.
 */
import type { InstitutionKind, MembershipStatus, UserRole } from '../api/auth'
import type { TransactionKind } from '../api/currency'
import type { PurchaseStatus } from '../api/market'

export const KIND_LABELS: Record<InstitutionKind, string> = {
  school: 'школа',
  camp: 'лагерь',
}

export const TRANSACTION_KIND_LABELS: Record<TransactionKind, string> = {
  manual_accrual: 'Начисление',
  reversal: 'Сторно',
  purchase: 'Покупка',
  purchase_refund: 'Возврат за покупку',
}

export const PURCHASE_STATUS_LABELS: Record<PurchaseStatus, string> = {
  pending: 'Ожидает решения',
  fulfilled: 'Выдано',
  rejected: 'Отклонено',
}

export const ROLE_LABELS: Record<UserRole, string> = {
  student: 'ученик',
  teacher: 'преподаватель',
  institution_admin: 'администратор',
}

export const STATUS_LABELS: Record<MembershipStatus, string> = {
  invited: 'приглашение не принято',
  active: 'доступ активен',
  suspended: 'доступ приостановлен',
}
