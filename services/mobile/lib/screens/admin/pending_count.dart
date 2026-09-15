/// Счётчик заявок `pending` для бейджа на вкладке «Маркет» администратора —
/// зеркало семантики `services/web/src/navigation/usePendingPurchasesCount.ts`,
/// без опроса по таймеру.
///
/// Источник — `listPurchases(..., status: pending)`, значение — длина
/// списка. Запрос уходит только для `institution_admin` с выбранным
/// учреждением; для остальных ролей и до выбора учреждения значение — `null`
/// без запроса. При ошибке счётчик тоже `null` — отдельного экрана ошибки
/// нет, бейдж просто не показывается.
///
/// Обновление вместо `pathname`/`focus`/`visibilitychange` веба:
/// - `ref.invalidate(pendingPurchasesCountProvider)` при переключении вкладок
///   в `_AppShell` (`app_router.dart`) — аналог смены маршрута;
/// - `AppLifecycleState.resumed` там же — аналог возврата фокуса вкладке.
///
/// Экраны шага 2 (выдача/отказ по заявке) читают и инвалидируют этот же
/// провайдер тем же способом — `ref.invalidate(pendingPurchasesCountProvider)`.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart' as auth_api;
import '../../api/market_admin_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// `null` — счётчик скрыт (не admin, нет учреждения или запрос упал).
final pendingPurchasesCountProvider = FutureProvider<int?>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null || institution.role != auth_api.UserRole.institutionAdmin) {
    return null;
  }
  final client = ref.watch(apiClientProvider);
  try {
    final purchases = await listPurchases(
      client,
      institution.id,
      filter: const ListPurchasesFilter(status: PurchaseStatus.pending),
    );
    return purchases.length;
  } catch (_) {
    return null;
  }
}, retry: _noRetry);
