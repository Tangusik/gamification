import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/router/app_router.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('имя показывается и сохраняется', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    String? sentFullName;
    final container = await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson(fullName: 'Иван Иванов')),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
      'PATCH /users/me': (o) async {
        sentFullName = (o.data as Map<String, dynamic>)['full_name'] as String?;
        return jsonResponse(200, userJson(fullName: sentFullName));
      },
    });

    container.read(goRouterProvider).go('/profile');
    await pumpFrames(tester);
    expect(find.text('Профиль'), findsWidgets);
    expect(find.text('Иван Иванов'), findsOneWidget);

    await tester.enterText(find.byType(TextField).first, 'Пётр Петров');
    await tapAndSettle(tester, find.text('Сохранить имя'));

    expect(sentFullName, 'Пётр Петров');
    expect(container.read(sessionProvider).user?.fullName, 'Пётр Петров');
  });

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
