/// Человеческие подписи для перечислений — зеркало
/// `services/web/src/i18n/labels.ts`. Только то, что нужно этапу 09a:
/// подписи ролей, статусов членства, типов учреждения и операций валюты
/// (перечисления `institution_admin`/каталога — 09b/09c — не переносятся,
/// пока их модели не появились в `lib/api/`).
library;

import '../api/auth_api.dart';
import '../api/currency_api.dart';
import '../api/market_api.dart';

const Map<InstitutionKind, String> kindLabels = {
  InstitutionKind.school: 'школа',
  InstitutionKind.camp: 'лагерь',
};

const Map<TransactionKind, String> transactionKindLabels = {
  TransactionKind.manualAccrual: 'Начисление',
  TransactionKind.reversal: 'Сторно',
  TransactionKind.purchase: 'Покупка',
  TransactionKind.purchaseRefund: 'Возврат за покупку',
};

const Map<PurchaseStatus, String> purchaseStatusLabels = {
  PurchaseStatus.pending: 'Ожидает решения',
  PurchaseStatus.fulfilled: 'Выдано',
  PurchaseStatus.rejected: 'Отклонено',
};

const Map<UserRole, String> roleLabels = {
  UserRole.student: 'ученик',
  UserRole.teacher: 'преподаватель',
  UserRole.institutionAdmin: 'администратор',
};

const Map<MembershipStatus, String> statusLabels = {
  MembershipStatus.invited: 'приглашение не принято',
  MembershipStatus.active: 'доступ активен',
  MembershipStatus.suspended: 'доступ приостановлен',
};
