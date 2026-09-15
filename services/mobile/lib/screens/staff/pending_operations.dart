/// Хранилища незавершённых `operation_id` начисления и сторно — вне `State`
/// экрана карточки ученика, по тому же приёму, что [PendingPurchases] в
/// `lib/screens/student/providers.dart` (находка С3 ревью безопасности,
/// `.claude/plans/09-mobile-app.md`, раздел Ч6): `StudentCardScreen` может
/// быть пересобран (redirect на вход после 401, на `/institutions`, на
/// `/password`, смена роли), а провайдер без `autoDispose` переживает такую
/// пересборку, пока жив `ProviderContainer` (процесс приложения).
///
/// Ключ начисления — пользователь (кто начисляет) + учреждение + ученик:
/// один и тот же администратор/преподаватель не должен спутать попытку
/// начисления одному ученику с попыткой другому, а смена учреждения или
/// пользователя на устройстве не должна переиспользовать чужой id.
///
/// Ключ сторно — пользователь + учреждение + id сторнируемой транзакции:
/// сторно разных транзакций — разные попытки.
///
/// Политика смены id одна и та же для обоих хранилищ: id заводится при
/// первой попытке и остаётся тем же при сети, таймауте, 5xx и доменных
/// отказах вроде `STUDENT_SUSPENDED` — повтор с тем же id остаётся
/// идемпотентным. Сбрасывается id только при однозначном исходе:
/// - успех (сервер отвечает 201/200);
/// - `OPERATION_ID_CONFLICT` — id уже занят операцией с другими параметрами,
///   повтор с ним никогда не пройдёт;
/// - для сторно ещё `TRANSACTION_ALREADY_REVERSED`.
/// Решение сбрасывать id на этих двух кодах — ведущего: иначе попытка вне
/// `State` застряла бы навсегда без способа отправить операцию заново.
///
/// **Находка ревью безопасности (medium, `.claude/plans/09-mobile-app.md`
/// не относится — правка отдельного тикета).** `PendingAccruals` хранит
/// вместе с id ещё и **отправленное тело** (`amount`, `comment`): если id
/// пережил отказ (таймаут/5xx/пересборка экрана), а пользователь успел
/// поменять сумму или комментарий, повтор с тем же id, но другим телом либо
/// уходит в `OPERATION_ID_CONFLICT` (сервер видит несовпадение и отклоняет),
/// либо — при поле, которое сервер не сверяет, — тихо расходится с тем, что
/// реально было отправлено первой попыткой. Фиксация тела на экране не даёт
/// повторной отправке разъехаться с тем, что уже могло уйти на сервер: пока
/// попытка не закрыта, поля формы показывают ровно то тело и заблокированы
/// для правки — экран (`student_card_screen.dart`) решает, как это отрисовать.
/// У сторно тела нет (только id сторнируемой транзакции), поэтому у
/// `PendingReversals` эта проблема не возникает и хранилище не меняется.
library;

import 'package:flutter/foundation.dart' show immutable;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/operation_id.dart';

/// Ключ незавершённой попытки начисления.
@immutable
class PendingAccrualKey {
  const PendingAccrualKey({required this.userId, required this.institutionId, required this.studentUserId});

  /// Пользователь, который начисляет (teacher/admin), не ученик.
  final String userId;
  final String institutionId;
  final String studentUserId;

  @override
  bool operator ==(Object other) =>
      other is PendingAccrualKey &&
      other.userId == userId &&
      other.institutionId == institutionId &&
      other.studentUserId == studentUserId;

  @override
  int get hashCode => Object.hash(userId, institutionId, studentUserId);
}

/// Незавершённая попытка начисления: id вместе с телом, которое реально
/// ушло в первом запросе. Повтор всегда отправляет именно эти [amount] и
/// [comment] — не то, что сейчас может быть введено в форме.
@immutable
class PendingAccrualAttempt {
  const PendingAccrualAttempt({required this.operationId, required this.amount, this.comment});

  final String operationId;
  final int amount;
  final String? comment;

  @override
  bool operator ==(Object other) =>
      other is PendingAccrualAttempt &&
      other.operationId == operationId &&
      other.amount == amount &&
      other.comment == comment;

  @override
  int get hashCode => Object.hash(operationId, amount, comment);
}

class PendingAccruals extends Notifier<Map<PendingAccrualKey, PendingAccrualAttempt>> {
  @override
  Map<PendingAccrualKey, PendingAccrualAttempt> build() => const {};

  /// Начать попытку начисления [amount]/[comment] для [key] или вернуть уже
  /// идущую. Если попытка для [key] уже есть, [amount] и [comment]
  /// игнорируются — тело зафиксировано на первой отправке, повтор обязан
  /// быть идентичным ей.
  PendingAccrualAttempt start(PendingAccrualKey key, {required int amount, String? comment}) {
    final existing = state[key];
    if (existing != null) return existing;
    final attempt = PendingAccrualAttempt(operationId: newOperationId(), amount: amount, comment: comment);
    state = {...state, key: attempt};
    return attempt;
  }

  /// Забыть попытку — после успеха или `OPERATION_ID_CONFLICT`.
  void clear(PendingAccrualKey key) {
    if (!state.containsKey(key)) return;
    final next = Map<PendingAccrualKey, PendingAccrualAttempt>.from(state)..remove(key);
    state = next;
  }
}

final pendingAccrualsProvider =
    NotifierProvider<PendingAccruals, Map<PendingAccrualKey, PendingAccrualAttempt>>(PendingAccruals.new);

/// Ключ незавершённой попытки сторно.
@immutable
class PendingReversalKey {
  const PendingReversalKey({required this.userId, required this.institutionId, required this.transactionId});

  /// Пользователь, который сторнирует (admin), не ученик.
  final String userId;
  final String institutionId;

  /// Id сторнируемого начисления.
  final String transactionId;

  @override
  bool operator ==(Object other) =>
      other is PendingReversalKey &&
      other.userId == userId &&
      other.institutionId == institutionId &&
      other.transactionId == transactionId;

  @override
  int get hashCode => Object.hash(userId, institutionId, transactionId);
}

class PendingReversals extends Notifier<Map<PendingReversalKey, String>> {
  @override
  Map<PendingReversalKey, String> build() => const {};

  /// Вернуть `operation_id` уже идущей попытки для [key] или завести новый.
  String take(PendingReversalKey key) {
    final existing = state[key];
    if (existing != null) return existing;
    final operationId = newOperationId();
    state = {...state, key: operationId};
    return operationId;
  }

  /// Забыть попытку — после успеха, `OPERATION_ID_CONFLICT` или
  /// `TRANSACTION_ALREADY_REVERSED`.
  void clear(PendingReversalKey key) {
    if (!state.containsKey(key)) return;
    final next = Map<PendingReversalKey, String>.from(state)..remove(key);
    state = next;
  }
}

final pendingReversalsProvider = NotifierProvider<PendingReversals, Map<PendingReversalKey, String>>(
  PendingReversals.new,
);
