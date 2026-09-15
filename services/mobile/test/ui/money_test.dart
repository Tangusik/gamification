import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/money.dart';

void main() {
  testWidgets('положительная сумма разбивается по разрядам без знака', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Money(amount: 1240))));
    expect(find.text('1 240'), findsOneWidget);
  });

  testWidgets('отрицательная сумма получает знак минус', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Money(amount: -85))));
    expect(find.text('−85'), findsOneWidget);
  });

  testWidgets('showPlus добавляет плюс для положительной суммы', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Money(amount: 50, showPlus: true))));
    expect(find.text('+50'), findsOneWidget);
  });
}
