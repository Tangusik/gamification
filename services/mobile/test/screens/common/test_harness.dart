// Общий стенд для widget-тестов Ч5: тот же приём, что в `test/router/app_router_test.dart`
// — реальный `MyApp` (роутер + сессия) поверх фейковой сети, без обхода
// собственной логики экранов.
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/main.dart';

import '../../auth/test_support.dart';

typedef Routes = Map<String, Future<ResponseBody> Function(RequestOptions)>;

Future<ResponseBody> Function(RequestOptions) dispatchRoutes(Routes routes) {
  return (options) async {
    final key = '${options.method} ${options.path}';
    final handler = routes[key];
    if (handler == null) {
      throw StateError('Нет фейкового обработчика для "$key"');
    }
    return handler(options);
  };
}

ProviderContainer buildTestContainer(TokenStorage storage, Routes routes) {
  final container = ProviderContainer(
    overrides: [
      tokenStorageProvider.overrideWithValue(storage),
      apiClientProvider.overrideWithValue(buildFakeApiClient(dispatchRoutes(routes))),
    ],
  );
  container.read(sessionProvider);
  return container;
}

/// Прогнать фиксированное число кадров вместо `pumpAndSettle()`: на
/// `AuthPendingScreen` крутится неопределённый индикатор, который не
/// «успокаивается» сам.
Future<void> pumpFrames(WidgetTester tester, [int times = 20]) async {
  for (var i = 0; i < times; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<ProviderContainer> pumpTestApp(WidgetTester tester, TokenStorage storage, Routes routes) async {
  final container = buildTestContainer(storage, routes);
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const MyApp()));
  await pumpFrames(tester);
  return container;
}

/// Нажать кнопку, за которой стоит сетевой запрос: обычный `tap()` не
/// продвигает реальный `await` в автоматической FakeAsync-среде
/// `flutter test`, нужен `runAsync()` (находка Ч3). Ждём несколькими
/// короткими реальными паузами внутри одной сессии `runAsync`, а не одной —
/// иначе фоновая цепочка `Future` продолжает жить и в реальном времени уже
/// после завершения теста.
Future<void> tapAndSettle(WidgetTester tester, Finder finder, {int cycles = 20}) async {
  await tester.runAsync(() async {
    await tester.tap(finder);
    for (var i = 0; i < cycles; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
  });
  await pumpFrames(tester);
}
