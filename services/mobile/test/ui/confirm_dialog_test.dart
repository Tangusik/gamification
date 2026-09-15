import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/confirm_dialog.dart';

void main() {
  testWidgets('при открытии фокус стоит на кнопке «Отмена»', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => OutlinedButton(
              onPressed: () => showConfirmDialog(
                context,
                title: 'Удалить группу',
                confirmLabel: 'Удалить',
                danger: true,
              ),
              child: const Text('Открыть'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Открыть'));
    await tester.pumpAndSettle();

    final cancelFinder = find.widgetWithText(OutlinedButton, 'Отмена');
    expect(cancelFinder, findsOneWidget);
    final cancelWidget = tester.widget<OutlinedButton>(cancelFinder);
    expect(cancelWidget.focusNode?.hasFocus, isTrue);
  });

  testWidgets('подтверждение возвращает true', (tester) async {
    bool? result;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Builder(
            builder: (context) => OutlinedButton(
              onPressed: () async {
                result = await showConfirmDialog(context, title: 'Заголовок', confirmLabel: 'ОК');
              },
              child: const Text('Открыть'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Открыть'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'ОК'));
    await tester.pumpAndSettle();

    expect(result, isTrue);
  });
}
