import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/student/history_screen.dart';

import 'test_support.dart';

void main() {
  testWidgets('история показывает обе секции с данными', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(
        200,
        currencyAccountJson(balance: 100, transactions: [transactionJson(amount: 15)]),
      ),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, [purchaseJson(title: 'Пропуск ДЗ')]),
    });

    await pumpScreen(tester, const HistoryScreen(), adapter: adapter);

    expect(find.text('ОПЕРАЦИИ ПО ВАЛЮТЕ'), findsOneWidget);
    expect(find.text('МОИ ПОКУПКИ'), findsOneWidget);
    expect(find.text('+15'), findsOneWidget);
    expect(find.textContaining('Пропуск ДЗ'), findsOneWidget);
  });

  testWidgets('обе секции пусты — оба пустых состояния', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async =>
          jsonResponse(200, currencyAccountJson(balance: 0, transactions: const [])),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const HistoryScreen(), adapter: adapter);

    expect(find.text('Операций пока нет'), findsOneWidget);
    expect(find.text('Покупок пока нет'), findsOneWidget);
  });
}
