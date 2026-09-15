// Unit-тесты хранилищ незавершённых `operation_id` начисления и сторно —
// тот же приём, что `test/screens/student/pending_purchases_test.dart`.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/pending_operations.dart';

void main() {
  group('PendingAccruals', () {
    test('одна и та же попытка возвращает один и тот же operation_id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const key = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      expect(
        pending.start(key, amount: 10).operationId,
        pending.start(key, amount: 10).operationId,
      );
    });

    test('повторный start игнорирует новые amount/comment — тело зафиксировано', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const key = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      final first = pending.start(key, amount: 50, comment: 'за домашку');
      final second = pending.start(key, amount: 5, comment: 'другое');

      expect(second, first);
      expect(second.amount, 50);
      expect(second.comment, 'за домашку');
    });

    test('другой ученик даёт другой id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const keyA = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      const keyB = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-2');
      expect(pending.start(keyA, amount: 10).operationId, isNot(pending.start(keyB, amount: 10).operationId));
    });

    test('другой пользователь (начисляющий) при том же ученике даёт другой id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const keyA = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      const keyB = PendingAccrualKey(userId: 'staff-2', institutionId: 'inst-1', studentUserId: 'student-1');
      expect(pending.start(keyA, amount: 10).operationId, isNot(pending.start(keyB, amount: 10).operationId));
    });

    test('другое учреждение при тех же людях даёт другой id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const keyA = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      const keyB = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-2', studentUserId: 'student-1');
      expect(pending.start(keyA, amount: 10).operationId, isNot(pending.start(keyB, amount: 10).operationId));
    });

    test('clear забывает попытку — следующий start заводит новый id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      const key = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');
      final first = pending.start(key, amount: 10);
      pending.clear(key);
      expect(pending.start(key, amount: 10).operationId, isNot(first.operationId));
    });

    test('clear несуществующего ключа не падает', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingAccrualsProvider.notifier);

      expect(
        () => pending.clear(
          const PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1'),
        ),
        returnsNormally,
      );
    });

    test('провайдер без autoDispose переживает потерю всех наблюдателей', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      const key = PendingAccrualKey(userId: 'staff-1', institutionId: 'inst-1', studentUserId: 'student-1');

      final attempt = container.read(pendingAccrualsProvider.notifier).start(key, amount: 10);
      final sub = container.listen(pendingAccrualsProvider, (_, _) {});
      sub.close();

      expect(container.read(pendingAccrualsProvider.notifier).start(key, amount: 999), attempt);
    });
  });

  group('PendingReversals', () {
    test('одна и та же попытка возвращает один и тот же operation_id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingReversalsProvider.notifier);

      const key = PendingReversalKey(userId: 'admin-1', institutionId: 'inst-1', transactionId: 'tx-1');
      expect(pending.take(key), pending.take(key));
    });

    test('другая транзакция даёт другой id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingReversalsProvider.notifier);

      const keyA = PendingReversalKey(userId: 'admin-1', institutionId: 'inst-1', transactionId: 'tx-1');
      const keyB = PendingReversalKey(userId: 'admin-1', institutionId: 'inst-1', transactionId: 'tx-2');
      expect(pending.take(keyA), isNot(pending.take(keyB)));
    });

    test('clear забывает попытку — следующий take заводит новый id', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      final pending = container.read(pendingReversalsProvider.notifier);

      const key = PendingReversalKey(userId: 'admin-1', institutionId: 'inst-1', transactionId: 'tx-1');
      final first = pending.take(key);
      pending.clear(key);
      expect(pending.take(key), isNot(first));
    });

    test('провайдер без autoDispose переживает потерю всех наблюдателей', () {
      final container = ProviderContainer();
      addTearDown(container.dispose);
      const key = PendingReversalKey(userId: 'admin-1', institutionId: 'inst-1', transactionId: 'tx-1');

      final id = container.read(pendingReversalsProvider.notifier).take(key);
      final sub = container.listen(pendingReversalsProvider, (_, _) {});
      sub.close();

      expect(container.read(pendingReversalsProvider.notifier).take(key), id);
    });
  });
}
