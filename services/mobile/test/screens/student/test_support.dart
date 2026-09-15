// Общие фикстуры для тестов экранов ученика — тот же приём подмены сети, что
// в `test/auth/test_support.dart` (используется здесь только на чтение).
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
  /// `operation_id` между попытками.
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

/// Сессия студента с готовым учреждением — минуя вход и `_bootstrap`, чтобы
/// тесты экранов не зависели от сети сессии.
class FixedSessionNotifier extends SessionNotifier {
  FixedSessionNotifier(this._state);

  final SessionState _state;

  @override
  SessionState build() => _state;
}

SessionState studentSession({String institutionId = 'inst-1', String? currencyName = 'коины'}) {
  return SessionState(
    status: SessionStatus.authed,
    token: 't',
    user: auth_api.User(
      id: 'u1',
      email: 'student@example.com',
      isActive: true,
      isSuperuser: false,
      isVerified: true,
      createdAt: DateTime.utc(2026, 1, 1),
      mustChangePassword: false,
    ),
    institution: InstitutionContext(
      id: institutionId,
      role: auth_api.UserRole.student,
      name: 'Школа №1',
      currencyName: currencyName,
    ),
  );
}

Map<String, dynamic> privilegeJson({
  String id = 'p1',
  String title = 'Пропуск домашки',
  String? description = 'Одна работа без сдачи',
  int price = 100,
  int? stock = 5,
  bool isActive = true,
}) => {
  'id': id,
  'title': title,
  'description': description,
  'price': price,
  'stock': stock,
  'is_active': isActive,
};

Map<String, dynamic> purchaseJson({
  String id = 'pu1',
  String privilegeId = 'p1',
  String title = 'Пропуск домашки',
  int price = 100,
  String status = 'pending',
  String createdAt = '2026-09-01T10:00:00Z',
  String? resolvedAt,
}) => {
  'id': id,
  'privilege_id': privilegeId,
  'title': title,
  'price': price,
  'status': status,
  'created_at': createdAt,
  'resolved_at': resolvedAt,
};

Map<String, dynamic> currencyAccountJson({
  int balance = 100,
  List<Map<String, dynamic>> transactions = const [],
}) => {
  'balance': balance,
  'transactions': transactions,
};

/// Прогнать фиксированное число кадров вместо `pumpAndSettle()`: пока
/// `ScreenStateLoading` на экране, крутится неопределённый индикатор,
/// который никогда не «успокаивается» сам (тот же приём, что в
/// `test/router/app_router_test.dart`).
Future<void> pumpFrames(WidgetTester tester, [int times = 20]) async {
  for (var i = 0; i < times; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

/// Собрать `ProviderScope` с фейковым API и готовой сессией студента,
/// прогнать до устойчивого состояния.
Future<ProviderContainer> pumpScreen(
  WidgetTester tester,
  Widget screen, {
  required RecordingAdapter adapter,
  SessionState? session,
}) async {
  final container = ProviderContainer(
    overrides: [
      sessionProvider.overrideWith(() => FixedSessionNotifier(session ?? studentSession())),
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

Map<String, dynamic> transactionJson({
  String id = 't1',
  String kind = 'manual_accrual',
  int amount = 10,
  String? comment,
  String? createdByName = 'Иван Иванов',
  String createdByRole = 'teacher',
  String createdAt = '2026-09-01T10:00:00Z',
  String? reversesId,
}) => {
  'id': id,
  'kind': kind,
  'amount': amount,
  'comment': comment,
  'created_by_name': createdByName,
  'created_by_role': createdByRole,
  'created_at': createdAt,
  'reverses_id': reversesId,
};
