/// Riverpod-провайдеры главной teacher/admin (09b) — перенос веток
/// `AdminDashboard`/`TeacherDashboard` из `services/web/src/pages/HomePage.tsx`.
///
/// Заявки на выдачу — отдельный провайдер, а не переиспользование
/// `pendingPurchasesCountProvider` (`lib/screens/admin/pending_count.dart`):
/// тот провайдер глотает ошибку и отдаёт `null` (у него только бейдж, без
/// экрана «Повторить»), а веб на главной показывает саму ошибку с кнопкой
/// повтора — карточке «ЗАЯВКИ» нужен обычный `AsyncValue`, а не число с
/// потерянной ошибкой.
///
/// Список групп для карточки «МОИ ГРУППЫ» teacher переиспользует
/// [staffGroupsProvider] из `students_providers.dart` — тот же запрос
/// `GET /groups`, второй провайдер на тот же ресурс не заводится.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/market_admin_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Число заявок в статусе `pending` — карточка «ЗАЯВКИ» на главной admin.
final staffPendingPurchasesProvider = FutureProvider.autoDispose<int>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  final purchases = await listPurchases(
    client,
    institution.id,
    filter: const ListPurchasesFilter(status: PurchaseStatus.pending),
  );
  return purchases.length;
}, retry: _noRetry);
