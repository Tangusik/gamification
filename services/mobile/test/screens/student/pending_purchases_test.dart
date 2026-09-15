// Unit-тесты хранилища незавершённых попыток покупки (`pendingPurchasesProvider`) —
// находка С3 ревью безопасности (`.claude/plans/09-mobile-app.md`, раздел Ч6):
// id должен различаться для разных пользователей и учреждений и не должен
// смешиваться между ними.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/student/providers.dart';

void main() {
  test('одна и та же попытка возвращает один и тот же operation_id', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final pending = container.read(pendingPurchasesProvider.notifier);

    const key = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1');
    final first = pending.take(key);
    final second = pending.take(key);

    expect(first, second);
  });

  test('разный пользователь при том же учреждении и привилегии даёт разный id', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final pending = container.read(pendingPurchasesProvider.notifier);

    const keyA = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1');
    const keyB = PendingPurchaseKey(userId: 'u2', institutionId: 'inst-1', privilegeId: 'p1');

    expect(pending.take(keyA), isNot(pending.take(keyB)));
  });

  test('разное учреждение при том же пользователе и привилегии даёт разный id', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final pending = container.read(pendingPurchasesProvider.notifier);

    const keyA = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1');
    const keyB = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-2', privilegeId: 'p1');

    expect(pending.take(keyA), isNot(pending.take(keyB)));
  });

  test('clear забывает попытку — следующий take заводит новый id', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final pending = container.read(pendingPurchasesProvider.notifier);

    const key = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1');
    final first = pending.take(key);
    pending.clear(key);
    final second = pending.take(key);

    expect(first, isNot(second));
  });

  test('clear несуществующего ключа не падает', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    final pending = container.read(pendingPurchasesProvider.notifier);

    expect(
      () => pending.clear(const PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1')),
      returnsNormally,
    );
  });

  test('провайдер без autoDispose переживает потерю всех наблюдателей', () {
    final container = ProviderContainer();
    addTearDown(container.dispose);
    const key = PendingPurchaseKey(userId: 'u1', institutionId: 'inst-1', privilegeId: 'p1');

    final id = container.read(pendingPurchasesProvider.notifier).take(key);

    // Имитация пересборки экрана: подписка через listen создаётся и сразу
    // закрывается — у обычного `autoDispose`-провайдера состояние в этот
    // момент обнулилось бы.
    final sub = container.listen(pendingPurchasesProvider, (_, _) {});
    sub.close();

    expect(container.read(pendingPurchasesProvider.notifier).take(key), id);
  });
}
