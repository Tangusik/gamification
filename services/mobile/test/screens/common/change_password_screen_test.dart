import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('смена пароля снимает редирект на /password', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    final relogged = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    var meCalls = 0;
    final container = await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async {
        meCalls++;
        // Первый вызов — холодный старт (пароль ещё не менялся); после
        // успешного повторного входа сервер уже отдаёт свежего пользователя
        // без флага принудительной смены.
        return jsonResponse(200, userJson(mustChangePassword: meCalls == 1));
      },
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
      'PATCH /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: false)),
      // Смена пароля гасит все сессии на сервере — форма сама входит заново
      // тем же паролем, чтобы получить свежую пару токенов.
      'POST /users/auth/jwt/login': (o) async => jsonResponse(200, {
        'access_token': relogged,
        'token_type': 'bearer',
        'refresh_token': 'new-refresh',
      }),
    });
    expect(find.text('Смена пароля'), findsWidgets);

    await tester.enterText(find.byType(TextField).at(0), 'NewPassw0rd!');
    await tester.enterText(find.byType(TextField).at(1), 'NewPassw0rd!');

    await tapAndSettle(tester, find.text('Сохранить пароль'));

    expect(container.read(sessionProvider).user?.mustChangePassword, isFalse);
    expect(find.text('Смена пароля'), findsNothing);
    expect(find.text('Главная'), findsWidgets);
  });

  testWidgets(
    'неудачный повторный вход после смены пароля уводит в anon и не вызывает onSuccess (К4)',
    (tester) async {
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
        'GET /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: true)),
        'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
        'PATCH /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: false)),
        // Сервер уже погасил сессии сменой пароля — повторный вход не
        // проходит (например, сеть недоступна в этот момент).
        'POST /users/auth/jwt/login': (o) async {
          throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
        },
        'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
      });
      expect(find.text('Смена пароля'), findsWidgets);

      await tester.enterText(find.byType(TextField).at(0), 'NewPassw0rd!');
      await tester.enterText(find.byType(TextField).at(1), 'NewPassw0rd!');

      await tapAndSettle(tester, find.text('Сохранить пароль'));

      // Локальный выход (К4): сессия ушла в anon, роутер увёл на экран входа
      // — то есть `onSuccess` не сработал, иначе пользователь оказался бы на
      // главной с погашенной сессией.
      expect(container.read(sessionProvider).status, SessionStatus.anon);
      expect(find.text('Вход'), findsWidgets);
      expect(find.text('Главная'), findsNothing);
    },
  );

  testWidgets('несовпадение паролей показывает ошибку без запроса на сервер', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: true)),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
    });
    expect(find.text('Смена пароля'), findsWidgets);

    await tester.enterText(find.byType(TextField).at(0), 'NewPassw0rd!');
    await tester.enterText(find.byType(TextField).at(1), 'other');

    await tapAndSettle(tester, find.text('Сохранить пароль'));

    expect(find.text('Пароли не совпадают.'), findsOneWidget);
    expect(find.text('Смена пароля'), findsWidgets);
  });
}
