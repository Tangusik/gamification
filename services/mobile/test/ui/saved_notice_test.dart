import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/saved_notice.dart';

void main() {
  testWidgets('показывает уведомление «Сохранено» поверх SnackBar', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => OutlinedButton(
              onPressed: () => showSavedNotice(context),
              child: const Text('Сохранить'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Сохранить'));
    await tester.pump();

    expect(find.text('Сохранено'), findsOneWidget);
  });

  testWidgets('текст можно переопределить', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => OutlinedButton(
              onPressed: () => showSavedNotice(context, text: 'Обновлено'),
              child: const Text('Сохранить'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Сохранить'));
    await tester.pump();

    expect(find.text('Обновлено'), findsOneWidget);
  });
}
