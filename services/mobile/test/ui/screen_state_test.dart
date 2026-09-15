import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/screen_state.dart';

void main() {
  testWidgets('загрузка показывает индикатор', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ScreenStateLoading())));
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('ошибка показывает текст, код и кнопку «Повторить»', (tester) async {
    var retried = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ScreenStateError(
            message: 'Сеть недоступна',
            code: 'NETWORK_ERROR',
            onRetry: () => retried = true,
          ),
        ),
      ),
    );

    expect(find.textContaining('Сеть недоступна'), findsOneWidget);
    expect(find.textContaining('NETWORK_ERROR'), findsOneWidget);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Повторить'));
    expect(retried, isTrue);
  });

  testWidgets('пусто показывает сообщение и действие', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: ScreenStateEmpty(message: 'Пока пусто', action: Text('Добавить')),
        ),
      ),
    );

    expect(find.text('Пока пусто'), findsOneWidget);
    expect(find.text('Добавить'), findsOneWidget);
  });

  testWidgets('нет доступа показывает заголовок', (tester) async {
    await tester.pumpWidget(const MaterialApp(home: Scaffold(body: ScreenStateForbidden())));
    expect(find.text('Нет доступа'), findsOneWidget);
  });
}
