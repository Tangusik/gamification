// Smoke-тест: приложение стартует, сессия определяется и роутер показывает
// экран входа для анонима (нет сохранённого токена).
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/main.dart';

void main() {
  testWidgets('приложение стартует и анонима ведёт на вход', (WidgetTester tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [tokenStorageProvider.overrideWithValue(InMemoryTokenStorage())],
        child: const MyApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('Вход'), findsWidgets);
  });
}
