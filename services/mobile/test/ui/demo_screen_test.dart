import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/ui/demo_screen.dart';
import 'package:gamification_mobile/ui/design_tokens.dart';

void main() {
  testWidgets('кириллический заголовок в Press Start 2P рендерится без ошибок, шрифт из ассетов', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: const DemoScreen()));
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull);

    final titleFinder = find.text('Gamification');
    expect(titleFinder, findsOneWidget);

    final sectionFinder = find.text('Баланс');
    expect(sectionFinder, findsOneWidget);
    final sectionText = tester.widget<Text>(sectionFinder);
    expect(sectionText.style?.fontFamily, AppFonts.pixel);

    // Шрифт подгружен как ассет пакета, а не системный дефолт.
    expect(AppFonts.pixel, 'Press Start 2P');
  });

  testWidgets('переключение состояния экрана меняет содержимое', (tester) async {
    await tester.pumpWidget(MaterialApp(theme: buildAppTheme(), home: const DemoScreen()));

    await tester.tap(find.widgetWithText(OutlinedButton, 'Загрузка'));
    await tester.pump();
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Пусто'));
    await tester.pump();
    expect(find.text('Пока пусто'), findsOneWidget);
  });
}
