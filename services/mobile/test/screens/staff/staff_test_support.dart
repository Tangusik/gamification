// Общие фикстуры для тестов экранов teacher/admin (09b/09c) — тот же приём
// подмены сети, что в `test/screens/student/test_support.dart` (используется
// здесь только на чтение, не изменяется).
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/auth_api.dart' as auth_api;
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/ui/design_tokens.dart';

typedef Routes = Map<String, Future<ResponseBody> Function(RequestOptions options, Object? body)>;

/// Фейковый HTTP-адаптер, который дополнительно декодирует JSON-тело запроса
/// из потока байтов — `options.data` не годится, `dio` не гарантирует, что
/// поле остаётся тем же объектом после трансформации.
class RecordingAdapter implements HttpClientAdapter {
  RecordingAdapter(this._routes);

  final Routes _routes;

  /// Тела всех POST/PATCH-запросов в порядке отправки — для проверки
  /// `operation_id` между попытками и содержимого форм.
  final List<Map<String, dynamic>> requestBodies = [];

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    Object? body;
    if (requestStream != null) {
      final bytes = await requestStream.fold<List<int>>([], (acc, chunk) => acc..addAll(chunk));
      if (bytes.isNotEmpty) {
        body = jsonDecode(utf8.decode(bytes));
        if (body is Map<String, dynamic>) requestBodies.add(body);
      }
    }
    final key = '${options.method} ${options.path}';
    final handler = _routes[key];
    if (handler == null) {
      throw StateError('Нет фейкового обработчика для "$key"');
    }
    return handler(options, body);
  }

  @override
  void close({bool force = false}) {}
}

ApiClient buildFakeApiClient(RecordingAdapter adapter) {
  final dio = Dio(BaseOptions(validateStatus: (status) => status != null && status >= 200 && status < 300));
  dio.httpClientAdapter = adapter;
  return ApiClient(tokenProvider: () => 't', dio: dio);
}

ResponseBody jsonResponse(int statusCode, Object body) {
  return ResponseBody.fromString(
    jsonEncode(body),
    statusCode,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

/// Сессия с готовым учреждением, минуя вход и `_bootstrap` — та же идея, что
/// и `FixedSessionNotifier` ученика.
class FixedSessionNotifier extends SessionNotifier {
  FixedSessionNotifier(this._state);

  final SessionState _state;

  @override
  SessionState build() => _state;
}

SessionState teacherSession({String institutionId = 'inst-1', String? currencyName = 'коины'}) {
  return _staffSession(
    role: auth_api.UserRole.teacher,
    institutionId: institutionId,
    currencyName: currencyName,
  );
}

SessionState adminSession({String institutionId = 'inst-1', String? currencyName = 'коины'}) {
  return _staffSession(
    role: auth_api.UserRole.institutionAdmin,
    institutionId: institutionId,
    currencyName: currencyName,
  );
}

SessionState _staffSession({
  required auth_api.UserRole role,
  required String institutionId,
  required String? currencyName,
}) {
  return SessionState(
    status: SessionStatus.authed,
    token: 't',
    user: auth_api.User(
      id: 'u1',
      email: 'staff@example.com',
      isActive: true,
      isSuperuser: false,
      isVerified: true,
      createdAt: DateTime.utc(2026, 1, 1),
      mustChangePassword: false,
    ),
    institution: InstitutionContext(
      id: institutionId,
      role: role,
      name: 'Школа №1',
      currencyName: currencyName,
    ),
  );
}

/// Прогнать фиксированное число кадров вместо `pumpAndSettle()`: пока
/// `ScreenStateLoading` на экране, крутится неопределённый индикатор,
/// который никогда не «успокаивается» сам (тот же приём, что в
/// `test/screens/student/test_support.dart`).
Future<void> pumpFrames(WidgetTester tester, [int times = 20]) async {
  for (var i = 0; i < times; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Собрать `ProviderScope` с фейковым API и готовой сессией teacher/admin,
/// прогнать до устойчивого состояния. Возвращает контейнер — тот же
/// контейнер передаётся в [remountScreen] для проверки политики
/// `operation_id` между перемонтированиями.
Future<ProviderContainer> pumpScreen(
  WidgetTester tester,
  Widget screen, {
  required RecordingAdapter adapter,
  required SessionState session,
}) async {
  final container = ProviderContainer(
    overrides: [
      sessionProvider.overrideWith(() => FixedSessionNotifier(session)),
      apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: buildAppTheme(), home: screen),
    ),
  );
  await pumpFrames(tester);
  return container;
}

/// Снять текущий экран и смонтировать его заново **в том же
/// `ProviderContainer`** — им проверяется, что провайдеры вне `autoDispose`
/// (например, хранилище незавершённых `operation_id`) переживают
/// пересборку экрана, а `autoDispose`-провайдеры данных запрашивают заново.
Future<void> remountScreen(WidgetTester tester, ProviderContainer container, Widget screen) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await pumpFrames(tester, 1);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(theme: buildAppTheme(), home: screen),
    ),
  );
  await pumpFrames(tester);
}
