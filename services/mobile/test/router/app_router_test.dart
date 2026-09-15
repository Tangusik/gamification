import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/main.dart';
import 'package:gamification_mobile/router/app_router.dart';

import '../auth/test_support.dart';

typedef _Routes = Map<String, Future<ResponseBody> Function(RequestOptions)>;

Future<ResponseBody> Function(RequestOptions) _dispatch(_Routes routes) {
  return (options) async {
    final key = '${options.method} ${options.path}';
    final handler = routes[key];
    if (handler == null) {
      throw StateError('Нет фейкового обработчика для "$key"');
    }
    return handler(options);
  };
}

ProviderContainer _buildContainer(TokenStorage storage, _Routes routes) {
  final container = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(storage),
      apiClientProvider.overrideWithValue(buildFakeApiClient(_dispatch(routes))),
    ],
  );
  container.read(sessionProvider);
  return container;
}

/// Прогнать фиксированное число кадров вместо `pumpAndSettle()`: на
/// `AuthPendingScreen` крутится неопределённый индикатор, который никогда
/// не «успокаивается» сам — `pumpAndSettle()` в таком дереве виснет.
Future<void> _pumpFrames(WidgetTester tester, [int times = 20]) async {
  for (var i = 0; i < times; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<ProviderContainer> _pumpApp(WidgetTester tester, TokenStorage storage, _Routes routes) async {
  final container = _buildContainer(storage, routes);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const MyApp()));
  await _pumpFrames(tester);
  return container;
}

void main() {
  testWidgets('холодный старт с живым токеном и учреждением открывает главную', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    await _pumpApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
    });

    expect(find.text('Главная'), findsWidgets);
  });

  testWidgets('с истёкшим токеном открывается экран входа', (tester) async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: -1))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);

    await _pumpApp(tester, storage, {});

    expect(find.text('Вход'), findsWidgets);
  });

  testWidgets('must_change_password уводит на смену пароля даже при выбранном учреждении', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    await _pumpApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: true)),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
    });

    expect(find.text('Смена пароля'), findsWidgets);
  });

  testWidgets('403 INSTITUTION_CONTEXT_REQUIRED уводит на выбор учреждения', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    final container = await _pumpApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, [membershipJson(institutionId: institutionId)]),
      'GET /institutions/inst-1/purchases': (o) async =>
          jsonResponse(403, {'detail': 'INSTITUTION_CONTEXT_REQUIRED'}),
    });
    expect(find.text('Главная'), findsWidgets);

    // Реальный (не фейковый) `await` вне `tester.pump()` не продвигается в
    // автоматической FakeAsync-среде `flutter test` — нужен `runAsync()`.
    final client = container.read(apiClientProvider);
    await tester.runAsync(() async {
      try {
        await client.request<void>('/institutions/inst-1/purchases');
      } catch (_) {
        // Ошибка ожидаема — интересует переход после неё.
      }
    });
    await _pumpFrames(tester);

    expect(find.text('Мои учреждения'), findsWidgets);
  });

  testWidgets('401 во время работы уводит на вход', (tester) async {
    final institutionId = 'inst-1';
    final token = fakeJwt({
      'sub': 'u1',
      'institution_id': institutionId,
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId(institutionId);

    final container = await _pumpApp(tester, storage, {
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
        // Ошибка ожидаема — интересует переход после неё.
      }
    });
    await _pumpFrames(tester);

    expect(find.text('Вход'), findsWidgets);
  });

  testWidgets('после входа возврат на исходный маршрут', (tester) async {
    final storage = InMemoryTokenStorage();

    final container = await _pumpApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
      'POST /users/auth/jwt/login': (o) async => jsonResponse(
        200,
        tokenJson(fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))})),
      ),
    });
    expect(find.text('Вход'), findsWidgets);

    // Аноним пытается открыть маршрут смены пароля — доступен только
    // авторизованным, но контекст учреждения не требует.
    container.read(goRouterProvider).go('/password');
    await _pumpFrames(tester);
    expect(find.text('Вход'), findsWidgets);

    await tester.runAsync(
      () => container.read(sessionProvider.notifier).login('user@example.com', 'password'),
    );
    await _pumpFrames(tester);

    expect(find.text('Смена пароля'), findsWidgets);
  });
}
