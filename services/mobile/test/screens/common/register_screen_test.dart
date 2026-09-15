import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/router/app_router.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('регистрация входит автоматически и уводит с анонимных экранов', (tester) async {
    final loginToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});

    final container = await pumpTestApp(tester, InMemoryTokenStorage(), {
      'POST /users/auth/register': (o) async => jsonResponse(201, userJson()),
      'POST /users/auth/jwt/login': (o) async => jsonResponse(200, tokenJson(loginToken)),
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
    });
    expect(find.text('Вход'), findsWidgets);

    container.read(goRouterProvider).go(registerPath);
    await pumpFrames(tester);
    expect(find.text('Регистрация'), findsWidgets);

    await tester.enterText(find.byType(TextField).at(0), 'new@example.com');
    await tester.enterText(find.byType(TextField).at(1), 'S3curePass!');

    await tapAndSettle(tester, find.text('Зарегистрироваться'));

    // Регистрация не выдаёт токен сама — вход выполнен вызовом login внутри
    // SessionNotifier.register, дальше сессия authed без учреждения ведёт
    // на онбординг.
    expect(container.read(sessionProvider).status, SessionStatus.authed);
    expect(find.text('Мои учреждения'), findsWidgets);
  });
}
