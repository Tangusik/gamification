import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/router/app_router.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('выход подтверждается диалогом и уводит на вход', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    var logoutCalled = false;
    final container = await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
      'POST /users/auth/jwt/logout': (o) async {
        logoutCalled = true;
        return jsonResponse(204, '');
      },
    });
    expect(find.text('Главная'), findsWidgets);

    container.read(goRouterProvider).go('/profile');
    await pumpFrames(tester);
    expect(find.text('Профиль'), findsWidgets);
    expect(find.text('user@example.com'), findsOneWidget);

    await tester.dragUntilVisible(find.text('Выход'), find.byType(ListView), const Offset(0, -300));
    await pumpFrames(tester);

    await tester.tap(find.text('Выход'));
    await pumpFrames(tester);

    // Диалог подтверждения открыт, выход ещё не выполнен.
    expect(find.text('Выйти из аккаунта на этом устройстве?'), findsOneWidget);
    expect(logoutCalled, isFalse);

    await tapAndSettle(tester, find.text('Выйти'));

    expect(logoutCalled, isTrue);
    expect(container.read(sessionProvider).status, SessionStatus.anon);
    expect(find.text('Вход'), findsWidgets);
  });

  testWidgets('отмена в диалоге не выполняет выход', (tester) async {
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
    });
    container.read(goRouterProvider).go('/profile');
    await pumpFrames(tester);

    await tester.dragUntilVisible(find.text('Выход'), find.byType(ListView), const Offset(0, -300));
    await pumpFrames(tester);

    await tester.tap(find.text('Выход'));
    await pumpFrames(tester);
    await tester.tap(find.text('Отмена'));
    await pumpFrames(tester);

    expect(container.read(sessionProvider).status, SessionStatus.authed);
    expect(find.text('Профиль'), findsWidgets);
  });
}
