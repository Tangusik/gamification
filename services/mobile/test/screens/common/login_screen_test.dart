import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('422 показывает ошибку у поля пароля', (tester) async {
    await pumpTestApp(tester, InMemoryTokenStorage(), {
      'POST /users/auth/jwt/login': (o) async => jsonResponse(422, {
        'detail': [
          {
            'loc': ['body', 'password'],
            'msg': 'Пароль слишком короткий.',
          },
        ],
      }),
    });
    expect(find.text('Вход'), findsWidgets);

    await tester.enterText(find.byType(TextField).at(0), 'user@example.com');
    await tester.enterText(find.byType(TextField).at(1), '123');

    await tapAndSettle(tester, find.text('Войти'));

    expect(find.text('Пароль слишком короткий.'), findsOneWidget);
    expect(find.text('Проверьте правильность заполнения полей.'), findsOneWidget);
  });

  testWidgets('код ошибки показывается текстом', (tester) async {
    final container = await pumpTestApp(tester, InMemoryTokenStorage(), {
      'POST /users/auth/jwt/login': (o) async => jsonResponse(400, {'detail': 'LOGIN_BAD_CREDENTIALS'}),
    });
    expect(find.text('Вход'), findsWidgets);

    await tester.enterText(find.byType(TextField).at(0), 'user@example.com');
    await tester.enterText(find.byType(TextField).at(1), 'wrong-password');

    await tester.runAsync(() async {
      await tester.tap(find.text('Войти'));
      await Future<void>.delayed(const Duration(milliseconds: 50));
    });
    await pumpFrames(tester);

    expect(find.text('Неверная почта или пароль.'), findsOneWidget);
    // Сессия осталась анонимной — 400 не сбросил и не подвинул статус.
    expect(container.read(sessionProvider).status, SessionStatus.anon);
  });

  testWidgets('notice «сессия истекла» показан на экране входа и сброшен', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    final container = await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
      'GET /institutions/inst-1/purchases': (o) async => jsonResponse(401, {'detail': 'Unauthorized'}),
    });
    expect(find.text('Главная'), findsWidgets);

    final client = container.read(apiClientProvider);
    await tester.runAsync(() async {
      try {
        await client.request<void>('/institutions/inst-1/purchases');
      } catch (_) {
        // Ошибка ожидаема — интересует переход и текст notice после неё.
      }
    });
    await pumpFrames(tester);

    expect(find.text('Вход'), findsWidgets);
    expect(find.text('Сессия истекла. Войдите заново.'), findsOneWidget);

    // Экран сам гасит notice в сессии после показа — повторный визит его не покажет.
    await pumpFrames(tester);
    expect(container.read(sessionProvider).notice, isNull);
  });
}
