import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/router/app_router.dart';
import 'package:gamification_mobile/screens/common/pending_invite.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('приём приглашения (в т.ч. повторный) отвечает 200 — это не ошибка', (tester) async {
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
      // Сервер идемпотентен: повторный приём того же приглашения тоже 200,
      // а не ошибка — фейковый бэкенд ничем не отличает первый вызов от
      // второго, как и настоящий.
      'POST /institutions/invitations/accept': (o) async =>
          jsonResponse(200, membershipJson(institutionId: 'inst-2', name: 'Лагерь «Звезда»', role: 'student')),
      'GET /institutions/inst-2/purchases': (o) async => jsonResponse(200, <Object>[]),
    });
    expect(find.text('Главная'), findsWidgets);

    container.read(goRouterProvider).go(invitePath);
    await pumpFrames(tester);
    expect(find.text('Приглашение'), findsWidgets);

    await tester.enterText(
      find.widgetWithText(TextField, 'Ссылка-приглашение'),
      'https://your-gamification.ru/invite#some-token',
    );
    await tapAndSettle(tester, find.text('Принять приглашение'));

    expect(find.textContaining('Готово: вы участник учреждения «Лагерь «Звезда»»'), findsOneWidget);
  });

  testWidgets('пустая ссылка показывает ошибку поля без запроса на сервер', (tester) async {
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
    container.read(goRouterProvider).go(invitePath);
    await pumpFrames(tester);

    await tapAndSettle(tester, find.text('Принять приглашение'));

    expect(find.text('Ссылка приглашения не содержит кода. Проверьте адрес.'), findsOneWidget);
  });

  testWidgets('аноним видит вход/регистрацию вместо кнопки приёма', (tester) async {
    final container = await pumpTestApp(tester, InMemoryTokenStorage(), {});
    expect(find.text('Вход'), findsWidgets);

    // /invite исключён из проверки на вход — редиректа на /login нет.
    container.read(goRouterProvider).go(invitePath);
    await pumpFrames(tester);

    expect(find.text('Приглашение'), findsWidgets);
    expect(find.text('Чтобы принять приглашение, войдите или зарегистрируйтесь.'), findsOneWidget);
    expect(find.text('Принять приглашение'), findsNothing);
    expect(find.widgetWithText(OutlinedButton, 'Войти'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Зарегистрироваться'), findsOneWidget);
  });

  testWidgets(
    'вошедший пользователь: переход на /invite внешним путём не вызывает приём без нажатия (С1)',
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
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
        // Если бы экран вызвал приём без нажатия, тест упал бы здесь — маршрут
        // для этого запроса не зарегистрирован.
      });
      expect(find.text('Главная'), findsWidgets);
      // Провайдер ожидающего приглашения пуст — никто в этом процессе не
      // вставлял ссылку и не жал «Войти» с этого экрана.
      expect(container.read(pendingInviteProvider), isNull);

      // Имитация explicit intent из чужого приложения на маршрут приёма —
      // без параметра `link` в самом маршруте (его там больше нет).
      container.read(goRouterProvider).go(invitePath);
      await pumpFrames(tester);

      expect(find.text('Приглашение'), findsWidgets);
      expect(find.text('Принять приглашение'), findsOneWidget);
      // Поле пустое — автоприём не сработал, кнопку никто не нажимал.
      expect(find.widgetWithText(TextField, 'Ссылка-приглашение'), findsOneWidget);
    },
  );

  testWidgets(
    'аноним вставляет ссылку, входит — приглашение принято автоматически, провайдер очищен',
    (tester) async {
      final institutionId = 'inst-2';
      final storage = InMemoryTokenStorage();

      final container = await pumpTestApp(tester, storage, {
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        'POST /users/auth/jwt/login': (o) async => jsonResponse(
          200,
          tokenJson(fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))})),
        ),
        'POST /institutions/invitations/accept': (o) async =>
            jsonResponse(200, membershipJson(institutionId: institutionId, name: 'Лагерь «Звезда»')),
        'GET /institutions/$institutionId/purchases': (o) async => jsonResponse(200, <Object>[]),
      });
      expect(find.text('Вход'), findsWidgets);

      container.read(goRouterProvider).go(invitePath);
      await pumpFrames(tester);
      expect(find.text('Приглашение'), findsWidgets);

      await tester.enterText(
        find.widgetWithText(TextField, 'Ссылка-приглашение'),
        'https://your-gamification.ru/invite#some-token',
      );
      await tester.tap(find.widgetWithText(OutlinedButton, 'Войти'));
      await pumpFrames(tester);
      expect(find.text('Вход'), findsWidgets);
      // Ссылка ушла в провайдер, а не в URL/query экрана входа.
      expect(container.read(pendingInviteProvider), isNotEmpty);

      await tester.enterText(find.widgetWithText(TextField, 'Почта'), 'user@example.com');
      await tester.enterText(find.widgetWithText(TextField, 'Пароль'), 'password');
      await tapAndSettle(tester, find.widgetWithText(OutlinedButton, 'Войти'));
      // Вход делает редирект на `/invite` только после следующего кадра, а
      // сам приём — из `addPostFrameCallback` внутри него: это отдельный
      // сетевой `await`, для которого нужен ещё один `runAsync`.
      await tester.runAsync(() async {
        for (var i = 0; i < 20; i++) {
          await Future<void>.delayed(const Duration(milliseconds: 20));
        }
      });
      await pumpFrames(tester);

      expect(find.textContaining('Готово: вы участник учреждения «Лагерь «Звезда»»'), findsOneWidget);
      expect(container.read(pendingInviteProvider), isNull);
    },
  );
}
