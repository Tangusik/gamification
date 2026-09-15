import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/student/student_home_screen.dart';

import 'test_support.dart';

void main() {
  testWidgets('главная показывает баланс и только последние 5 операций', (tester) async {
    final transactions = [
      for (final amount in [11, 22, 33, 44, 55, 66]) transactionJson(id: 't$amount', amount: amount),
    ];
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async =>
          jsonResponse(200, currencyAccountJson(balance: 250, transactions: transactions)),
    });

    await pumpScreen(tester, const StudentHomeScreen(), adapter: adapter);

    expect(find.text('250'), findsOneWidget);
    expect(find.text('коины'), findsOneWidget);

    for (final amount in [11, 22, 33, 44, 55]) {
      expect(find.text('+$amount'), findsOneWidget, reason: 'операция +$amount должна быть видна');
    }
    expect(find.text('+66'), findsNothing);
  });

  testWidgets('пустая история операций показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async =>
          jsonResponse(200, currencyAccountJson(balance: 0, transactions: const [])),
    });

    await pumpScreen(tester, const StudentHomeScreen(), adapter: adapter);

    expect(find.text('Операций пока нет.'), findsOneWidget);
  });

  testWidgets('сетевая ошибка показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async {
        throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
      },
    });

    await pumpScreen(tester, const StudentHomeScreen(), adapter: adapter);

    expect(find.widgetWithText(OutlinedButton, 'Повторить'), findsOneWidget);
  });
}
