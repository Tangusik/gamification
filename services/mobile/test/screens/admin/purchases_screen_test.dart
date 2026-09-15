import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/admin/purchases_screen.dart';

import '../staff/staff_test_support.dart';

Map<String, dynamic> _purchaseJson({
  String id = 'pu1',
  String privilegeId = 'p1',
  String title = 'Пропуск домашки',
  int price = 30,
  String status = 'pending',
  String createdAt = '2026-09-01T10:00:00Z',
  String? resolvedAt,
  String? userId = 'u2',
  String? userName = 'Ученик',
}) => {
  'id': id,
  'privilege_id': privilegeId,
  'title': title,
  'price': price,
  'status': status,
  'created_at': createdAt,
  'resolved_at': resolvedAt,
  'user_id': userId,
  'user_name': userName,
};

Future<void> _confirm(WidgetTester tester, String buttonLabel, String dialogLabel) async {
  await tester.tap(find.widgetWithText(OutlinedButton, buttonLabel));
  await tester.pumpAndSettle();
  await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text(dialogLabel)));
  await tester.pumpAndSettle();
  await pumpFrames(tester);
}

void main() {
  testWidgets('загрузка → данные', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [_purchaseJson()]),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Пропуск домашки'), findsOneWidget);
    expect(find.text('Ученик'), findsOneWidget);
  });

  testWidgets('ошибка загрузки показывает «Повторить»', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async {
        attempt += 1;
        if (attempt == 1) return jsonResponse(500, {'detail': 'BOOM'});
        return jsonResponse(200, [_purchaseJson()]);
      },
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());
    expect(find.text('Повторить'), findsWidgets);

    await tester.tap(find.text('Повторить').first);
    await pumpFrames(tester);

    expect(find.text('Пропуск домашки'), findsOneWidget);
  });

  testWidgets('пустая очередь и пустая история показывают тексты пустоты', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Новых заявок нет'), findsOneWidget);
    expect(find.text('Решённых покупок пока нет'), findsOneWidget);
  });

  testWidgets('отмена диалога выдачи не шлёт запрос', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [_purchaseJson()]),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Выдать'));
    await tester.pumpAndSettle();
    expect(find.text('Выдачу отменить нельзя.'), findsOneWidget);

    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Отмена')));
    await tester.pumpAndSettle();

    expect(adapter.requestBodies, isEmpty);
    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('выдача подтверждается и перечитывает счётчик', (tester) async {
    var pendingCalls = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async {
        pendingCalls += 1;
        return jsonResponse(200, pendingCalls == 1 ? [_purchaseJson()] : <Object>[]);
      },
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [
        _purchaseJson(status: 'fulfilled', resolvedAt: '2026-09-01T11:00:00Z'),
      ]),
      'POST /institutions/inst-1/purchases/pu1/fulfil': (o, b) async =>
          jsonResponse(200, _purchaseJson(status: 'fulfilled', resolvedAt: '2026-09-01T11:00:00Z')),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    await _confirm(tester, 'Выдать', 'Выдать');

    expect(find.text('Новых заявок нет'), findsOneWidget);
    // Счётчик заявок (`pendingPurchasesCountProvider`) перечитан отдельным
    // запросом того же вида, что и очередь на экране — обе инвалидации
    // приводят ко второму вызову.
    expect(pendingCalls, greaterThanOrEqualTo(2));
  });

  testWidgets('отклонение подтверждается текстом про возврат валюты', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'POST /institutions/inst-1/purchases/pu1/reject': (o, b) async =>
          jsonResponse(200, _purchaseJson(status: 'rejected', resolvedAt: '2026-09-01T11:00:00Z')),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Отклонить'));
    await tester.pumpAndSettle();
    expect(find.text('Валюта вернётся ученику.'), findsOneWidget);

    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Отклонить')));
    await tester.pumpAndSettle();
    await pumpFrames(tester);

    expect(find.byType(AlertDialog), findsNothing);
  });

  testWidgets('PURCHASE_ALREADY_RESOLVED показывает текст и перечитывает список', (tester) async {
    var pendingCalls = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async {
        pendingCalls += 1;
        return jsonResponse(200, pendingCalls == 1 ? [_purchaseJson()] : <Object>[]);
      },
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [
        _purchaseJson(status: 'fulfilled', resolvedAt: '2026-09-01T11:00:00Z'),
      ]),
      'POST /institutions/inst-1/purchases/pu1/fulfil': (o, b) async =>
          jsonResponse(409, {'detail': 'PURCHASE_ALREADY_RESOLVED'}),
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    await _confirm(tester, 'Выдать', 'Выдать');

    expect(find.textContaining('Покупка уже обработана'), findsOneWidget);
    // Список перечитан несмотря на ошибку — очередь снова пуста.
    expect(find.text('Новых заявок нет'), findsOneWidget);
  });

  testWidgets('двойное нажатие «Выдать» не шлёт второй запрос', (tester) async {
    var fulfilCalls = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, [_purchaseJson()]),
      'POST /institutions/inst-1/purchases/pu1/fulfil': (o, b) async {
        fulfilCalls += 1;
        await Future<void>.delayed(const Duration(milliseconds: 50));
        return jsonResponse(200, _purchaseJson(status: 'fulfilled'));
      },
    });

    await pumpScreen(tester, const PurchasesScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Выдать'));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Выдать')));
    await tester.pump();
    // Кнопка уже заблокирована — повторное нажатие до ответа сервера ничего
    // не отправляет.
    await tester.tap(find.widgetWithText(OutlinedButton, 'Сохраняем…'), warnIfMissed: false);
    await pumpFrames(tester);

    expect(fulfilCalls, 1);
  });
}
