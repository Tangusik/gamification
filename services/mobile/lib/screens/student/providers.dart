/// Riverpod-провайдеры данных ученика (09a) — баланс, каталог привилегий и
/// свои покупки. Без кодогенерации (В3 плана `09-mobile-app.md`).
///
/// Провайдеры читают учреждение из [sessionProvider]: экраны этого пакета
/// открываются только когда оно выбрано, за это отвечает `lib/router`.
/// `.autoDispose` — данные не нужны, пока вкладка не открыта.
///
/// **Автоматический повтор Riverpod 3 отключён** (`retry: _noRetry`): у
/// экранов уже есть явная кнопка «Повторить» (`ScreenStateError`), а
/// умолчание фреймворка — до 10 скрытых попыток с растущей паузой (до 6,4 с)
/// — держит `ScreenStateLoading` вместо ошибки надолго и не даёт
/// пользователю решить, когда повторять запрос.
library;

import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/currency_api.dart';
import '../../api/market_api.dart';
import '../../api/operation_id.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Баланс и последние операции текущего ученика.
final studentCurrencyProvider = FutureProvider.autoDispose<CurrencyAccount>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return getMyCurrency(client, institution.id);
}, retry: _noRetry);

/// Каталог привилегий — ученику отдаются только активные позиции.
final privilegesProvider = FutureProvider.autoDispose<List<Privilege>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPrivileges(client, institution.id);
}, retry: _noRetry);

/// Свои покупки — последние 50.
final myPurchasesProvider = FutureProvider.autoDispose<List<Purchase>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listMyPurchases(client, institution.id);
}, retry: _noRetry);

/// Ключ незавершённой попытки покупки: пользователь + учреждение +
/// привилегия — так id не переиспользуется для другого пользователя или
/// учреждения (например, после смены роли или входа другим аккаунтом на том
/// же устройстве).
@immutable
class PendingPurchaseKey {
  const PendingPurchaseKey({required this.userId, required this.institutionId, required this.privilegeId});

  final String userId;
  final String institutionId;
  final String privilegeId;

  @override
  bool operator ==(Object other) =>
      other is PendingPurchaseKey &&
      other.userId == userId &&
      other.institutionId == institutionId &&
      other.privilegeId == privilegeId;

  @override
  int get hashCode => Object.hash(userId, institutionId, privilegeId);
}

/// Хранилище незавершённых `operation_id` покупок — вне `State` экрана
/// (находка С3 ревью безопасности, `.claude/plans/09-mobile-app.md`, раздел
/// Ч6): `MarketScreen` уничтожается при redirect на вход после 401, на
/// `/institutions`, на `/password`, при смене роли — карта в `State` в этот
/// момент терялась, и повтор покупки после таймаута уходил с новым
/// `operation_id`, что давало двойное списание. Провайдер без `autoDispose`
/// переживает такие пересборки экрана, пока жив `ProviderContainer`
/// (процесс приложения).
///
/// Политика смены id — та же, что была в `State` (`operation_id.dart`): id
/// заводится при первой попытке и удаляется только после успеха или при
/// `PRICE_CHANGED`. При сети, таймауте, `OUT_OF_STOCK`, `INSUFFICIENT_BALANCE`
/// и 5xx повтор уходит с тем же id.
///
/// **Известное ограничение:** хранилище только в памяти процесса. Смерть
/// процесса Android (например, из-за нехватки памяти в фоне) карту теряет —
/// это не покрывается, хранилище на диске сейчас не делаем (решение
/// владельца, план 09a, Ч6).
class PendingPurchases extends Notifier<Map<PendingPurchaseKey, String>> {
  @override
  Map<PendingPurchaseKey, String> build() => const {};

  /// Вернуть `operation_id` уже идущей попытки для [key] или завести новый.
  String take(PendingPurchaseKey key) {
    final existing = state[key];
    if (existing != null) return existing;
    final operationId = newOperationId();
    state = {...state, key: operationId};
    return operationId;
  }

  /// Забыть попытку — вызывается после успеха или `PRICE_CHANGED`.
  void clear(PendingPurchaseKey key) {
    if (!state.containsKey(key)) return;
    final next = Map<PendingPurchaseKey, String>.from(state)..remove(key);
    state = next;
  }
}

final pendingPurchasesProvider = NotifierProvider<PendingPurchases, Map<PendingPurchaseKey, String>>(
  PendingPurchases.new,
);
