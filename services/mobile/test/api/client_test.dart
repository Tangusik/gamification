import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/api/errors.dart';

/// Подмена сети без новых зависимостей: свой `HttpClientAdapter`, который
/// либо отвечает заготовленным телом, либо бросает [DioException] — так
/// имитируются сетевой отказ и таймаут, для которых у `dio` нет ответа
/// вовсе.
class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this._handler);

  final Future<ResponseBody> Function(RequestOptions options) _handler;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    return _handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ApiClient buildClient(
  Future<ResponseBody> Function(RequestOptions options) handler, {
  String? token,
  ApiErrorHandlers handlers = const ApiErrorHandlers(),
  TokenRefresher? tokenRefresher,
  SessionGenerationProvider sessionGeneration = _zeroGeneration,
}) {
  final dio = Dio(BaseOptions(
    validateStatus: (status) => status != null && status >= 200 && status < 300,
  ));
  dio.httpClientAdapter = _FakeAdapter(handler);
  final client = ApiClient(tokenProvider: () => token, dio: dio, sessionGeneration: sessionGeneration);
  client.handlers = handlers;
  client.tokenRefresher = tokenRefresher;
  return client;
}

int _zeroGeneration() => 0;

ResponseBody jsonResponse(int statusCode, Object body) {
  return ResponseBody.fromString(
    jsonEncode(body),
    statusCode,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

void main() {
  test('успешный запрос возвращает разобранное тело', () async {
    final client = buildClient((options) async {
      expect(options.headers['Authorization'], 'Bearer t');
      return jsonResponse(200, {'ok': true});
    }, token: 't');

    final body = await client.request<Map<String, dynamic>>('/ping');

    expect(body, {'ok': true});
  });

  test('422 отдаёт ApiError с разобранным fieldErrors', () async {
    final client = buildClient((options) async {
      return jsonResponse(422, {
        'detail': [
          {
            'loc': ['body', 'password'],
            'msg': 'field required',
          },
        ],
      });
    });

    await expectLater(
      client.request<void>('/users/auth/register', method: 'POST'),
      throwsA(
        isA<ApiError>()
            .having((e) => e.status, 'status', 422)
            .having((e) => e.code, 'code', validationError)
            .having((e) => e.fieldErrors, 'fieldErrors', {'password': 'field required'}),
      ),
    );
  });

  test('401 отдаёт ApiError и вызывает onUnauthorized', () async {
    var called = false;
    final client = buildClient(
      (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
      handlers: ApiErrorHandlers(onUnauthorized: () => called = true),
    );

    await expectLater(
      client.request<void>('/users/me'),
      throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)),
    );
    expect(called, isTrue);
  });

  test('403 INSTITUTION_CONTEXT_REQUIRED вызывает свой обработчик', () async {
    var called = false;
    final client = buildClient(
      (options) async => jsonResponse(403, {'detail': 'INSTITUTION_CONTEXT_REQUIRED'}),
      handlers: ApiErrorHandlers(onInstitutionContextRequired: () => called = true),
    );

    await expectLater(
      client.request<void>('/institutions/1/me/currency'),
      throwsA(
        isA<ApiError>()
            .having((e) => e.status, 'status', 403)
            .having((e) => e.code, 'code', institutionContextRequired),
      ),
    );
    expect(called, isTrue);
  });

  test('код ошибки строкой из тела доходит без изменений', () async {
    final client = buildClient(
      (options) async => jsonResponse(409, {'detail': 'OPERATION_ID_CONFLICT'}),
    );

    await expectLater(
      client.request<void>('/institutions/1/purchases', method: 'POST'),
      throwsA(isA<ApiError>().having((e) => e.code, 'code', 'OPERATION_ID_CONFLICT')),
    );
  });

  test('сетевой отказ даёт networkError', () async {
    final client = buildClient((options) async {
      throw DioException(requestOptions: options, type: DioExceptionType.connectionError);
    });

    await expectLater(
      client.request<void>('/ping'),
      throwsA(isA<ApiError>().having((e) => e.code, 'code', networkError)),
    );
  });

  test('таймаут даёт networkError', () async {
    final client = buildClient((options) async {
      throw DioException(requestOptions: options, type: DioExceptionType.connectionTimeout);
    });

    await expectLater(
      client.request<void>('/ping'),
      throwsA(isA<ApiError>().having((e) => e.code, 'code', networkError)),
    );
  });

  group('обновление токена по 401 (план 10-refresh)', () {
    test('пять параллельных 401 → ровно один вызов refresh, все пять повторены и успешны', () async {
      var refreshCalls = 0;
      var currentToken = 'expired';
      var retriedRequests = 0;

      final dio = Dio(BaseOptions(
        validateStatus: (status) => status != null && status >= 200 && status < 300,
      ));
      dio.httpClientAdapter = _FakeAdapter((options) async {
        if (options.headers['Authorization'] == 'Bearer fresh') {
          retriedRequests++;
          return jsonResponse(200, {'ok': true});
        }
        return jsonResponse(401, {'detail': 'Unauthorized'});
      });
      final client = ApiClient(tokenProvider: () => currentToken, dio: dio);
      client.tokenRefresher = () async {
        refreshCalls++;
        // Задержка — чтобы все пять запросов успели прийти на 401 до того,
        // как обновление завершится, и действительно легли в одну очередь.
        await Future<void>.delayed(const Duration(milliseconds: 20));
        currentToken = 'fresh';
        return 'fresh';
      };

      final results = await Future.wait([
        for (var i = 0; i < 5; i++) client.request<Map<String, dynamic>>('/ping$i'),
      ]);

      expect(refreshCalls, 1);
      expect(retriedRequests, 5);
      for (final result in results) {
        expect(result, {'ok': true});
      }
    });

    test('без tokenRefresher 401 ведёт себя как раньше — сразу onUnauthorized', () async {
      var called = false;
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
        handlers: ApiErrorHandlers(onUnauthorized: () => called = true),
      );

      await expectLater(client.request<void>('/ping'), throwsA(isA<ApiError>()));
      expect(called, isTrue);
    });

    test('путь /users/auth/jwt/* исключён из обновления', () async {
      var refreshCalls = 0;
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'REFRESH_TOKEN_INVALID'}),
        tokenRefresher: () async {
          refreshCalls++;
          return 'fresh';
        },
      );

      await expectLater(
        client.request<void>('/users/auth/jwt/refresh', method: 'POST'),
        throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)),
      );
      expect(refreshCalls, 0);
    });

    test('повтор не зацикливается: 401 после обновления уходит в onUnauthorized', () async {
      var refreshCalls = 0;
      var onUnauthorizedCalls = 0;
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
        handlers: ApiErrorHandlers(onUnauthorized: () => onUnauthorizedCalls++),
        tokenRefresher: () async {
          refreshCalls++;
          return 'fresh';
        },
      );

      await expectLater(client.request<void>('/ping'), throwsA(isA<ApiError>()));

      expect(refreshCalls, 1);
      expect(onUnauthorizedCalls, 1);
    });
  });

  group('повтор refresh при сетевом сбое (К3, ревью 10-refresh)', () {
    test('сетевой сбой refresh даёт ровно один повтор — второй успешен, исходный запрос проходит', () async {
      var refreshCalls = 0;
      var currentToken = 'expired';
      final dio = Dio(BaseOptions(
        validateStatus: (status) => status != null && status >= 200 && status < 300,
      ));
      dio.httpClientAdapter = _FakeAdapter((options) async {
        if (options.headers['Authorization'] == 'Bearer fresh') {
          return jsonResponse(200, {'ok': true});
        }
        return jsonResponse(401, {'detail': 'Unauthorized'});
      });
      final client = ApiClient(tokenProvider: () => currentToken, dio: dio);
      client.refreshRetryDelay = Duration.zero;
      client.tokenRefresher = () async {
        refreshCalls++;
        if (refreshCalls == 1) {
          // Сбой без ответа сервера — ровно то, на что рассчитан повтор.
          throw const ApiError(0, networkError);
        }
        currentToken = 'fresh';
        return 'fresh';
      };

      final result = await client.request<Map<String, dynamic>>('/ping');

      expect(refreshCalls, 2);
      expect(result, {'ok': true});
    });

    test('401 от refresh не повторяется — ровно один запрос refresh', () async {
      var refreshCalls = 0;
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
        tokenRefresher: () async {
          refreshCalls++;
          throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
        },
      );
      client.refreshRetryDelay = Duration.zero;

      await expectLater(client.request<void>('/ping'), throwsA(isA<ApiError>()));
      expect(refreshCalls, 1);
    });
  });

  group('401 от refresh отдаётся исходному запросу отличимой ошибкой (К5, ревью 10-refresh)', () {
    test('исходный запрос получает ApiError(401), а не сетевую ошибку, onUnauthorized не вызывается', () async {
      var onUnauthorizedCalls = 0;
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
        handlers: ApiErrorHandlers(onUnauthorized: () => onUnauthorizedCalls++),
        tokenRefresher: () async => throw const ApiError(401, 'REFRESH_TOKEN_INVALID'),
      );

      await expectLater(
        client.request<void>('/ping'),
        throwsA(
          isA<ApiError>()
              .having((e) => e.status, 'status', 401)
              .having((e) => e.code, 'code', 'REFRESH_TOKEN_INVALID'),
        ),
      );
      expect(onUnauthorizedCalls, 0);
    });

    test('сетевой сбой refresh по-прежнему даёт исходному запросу сетевую ошибку', () async {
      final client = buildClient(
        (options) async => jsonResponse(401, {'detail': 'Unauthorized'}),
        tokenRefresher: () async => throw const ApiError(0, networkError),
      );
      client.refreshRetryDelay = Duration.zero;

      await expectLater(
        client.request<void>('/ping'),
        throwsA(isA<ApiError>().having((e) => e.code, 'code', networkError)),
      );
    });
  });

  group('поколение сессии на запросе (Р2, ревью 10-refresh)', () {
    test('401 запроса из уже закрытой сессии не запускает refresh и onUnauthorized', () async {
      var generation = 0;
      var refreshCalls = 0;
      var onUnauthorizedCalls = 0;
      final client = buildClient(
        (options) async {
          // Поколение меняется, пока запрос был в пути — эмулирует logout и
          // следующий вход, обогнавшие ответ сервера.
          generation++;
          return jsonResponse(401, {'detail': 'Unauthorized'});
        },
        handlers: ApiErrorHandlers(onUnauthorized: () => onUnauthorizedCalls++),
        tokenRefresher: () async {
          refreshCalls++;
          return 'fresh';
        },
        sessionGeneration: () => generation,
      );

      await expectLater(
        client.request<void>('/ping'),
        throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)),
      );

      expect(refreshCalls, 0);
      expect(onUnauthorizedCalls, 0);
    });

    test('401 в пределах того же поколения обновляется и повторяется как обычно', () async {
      var currentToken = 'expired';
      final dio = Dio(BaseOptions(
        validateStatus: (status) => status != null && status >= 200 && status < 300,
      ));
      dio.httpClientAdapter = _FakeAdapter((options) async {
        if (options.headers['Authorization'] == 'Bearer fresh') {
          return jsonResponse(200, {'ok': true});
        }
        return jsonResponse(401, {'detail': 'Unauthorized'});
      });
      final client = ApiClient(
        tokenProvider: () => currentToken,
        dio: dio,
        // Поколение — постоянное ненулевое значение: важно, что оно
        // одинаковое на исходном запросе и на повторе после обновления, а не
        // конкретно 0.
        sessionGeneration: () => 3,
      );
      client.tokenRefresher = () async {
        currentToken = 'fresh';
        return 'fresh';
      };

      final result = await client.request<Map<String, dynamic>>('/ping');

      expect(result, {'ok': true});
    });

    test(
        '401 повтора, догоняющего уже другую сессию, не запускает onUnauthorized '
        'и не повторяется снова', () async {
      var generation = 0;
      var requestCount = 0;
      var refreshCalls = 0;
      var onUnauthorizedCalls = 0;
      final client = buildClient(
        (options) async {
          requestCount++;
          // Первый ответ — обычный протухший токен в исходной сессии; после
          // refresh, пока повтор ещё в пути, сессия успевает смениться
          // (logout и новый вход), и повтор застаёт уже другое поколение.
          if (requestCount == 2) {
            generation++;
          }
          return jsonResponse(401, {'detail': 'Unauthorized'});
        },
        handlers: ApiErrorHandlers(onUnauthorized: () => onUnauthorizedCalls++),
        tokenRefresher: () async {
          refreshCalls++;
          return 'fresh';
        },
        sessionGeneration: () => generation,
      );

      await expectLater(
        client.request<void>('/ping'),
        throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)),
      );

      expect(refreshCalls, 1);
      expect(onUnauthorizedCalls, 0);
      expect(requestCount, 2);
    });
  });
}
