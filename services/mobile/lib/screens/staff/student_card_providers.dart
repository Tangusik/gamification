/// Riverpod-провайдеры карточки ученика (09b) — баланс с историей операций
/// и покупки одного ученика (только `institution_admin`, зеркало
/// `StudentCurrencyPage.tsx`).
///
/// `family` по `userId` — карточек одновременно открыто не больше одной, но
/// `family` даёт корректный autoDispose-ключ и защищает от утечки данных
/// одного ученика в провайдер другого при быстрой навигации между карточками.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/market_admin_api.dart';
import '../../api/staff_currency_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Баланс и история операций ученика [userId].
final studentCurrencyHistoryProvider =
    FutureProvider.autoDispose.family<CurrencyAccount, String>((ref, userId) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listStudentTransactions(client, institution.id, userId);
}, retry: _noRetry);

/// Покупки ученика [userId] — читает **только вызывающий код для admin**:
/// `teacher` не должен слать `GET .../purchases?user_id=` вовсе, поэтому
/// экран не имеет права смотреть (`ref.watch`) этот провайдер для не-admin —
/// сам провайдер не решает за экран, есть ли доступ, только читает данные.
final studentPurchasesProvider = FutureProvider.autoDispose.family<List<Purchase>, String>((ref, userId) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPurchases(client, institution.id, filter: ListPurchasesFilter(userId: userId));
}, retry: _noRetry);
