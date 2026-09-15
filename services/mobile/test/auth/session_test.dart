import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/errors.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';

import 'test_support.dart';

/// Хранилище, которое можно заставить бросать исключение на чтении или на
/// очистке — для Н4 (`readToken`) и Н5 (`clear`).
class _ThrowingStorage implements TokenStorage {
  _ThrowingStorage({this.throwOnRead = false, this.throwOnClear = false});

  final bool throwOnRead;
  final bool throwOnClear;
  final _inner = InMemoryTokenStorage();

  @override
  Future<String?> readToken() {
    if (throwOnRead) throw Exception('хранилище недоступно');
    return _inner.readToken();
  }

  @override
  Future<void> writeToken(String token) => _inner.writeToken(token);

  @override
  Future<String?> readRefreshToken() => _inner.readRefreshToken();

  @override
  Future<void> writeRefreshToken(String token) => _inner.writeRefreshToken(token);

  @override
  Future<String?> readLastInstitutionId() => _inner.readLastInstitutionId();

  @override
  Future<void> writeLastInstitutionId(String institutionId) => _inner.writeLastInstitutionId(institutionId);

  @override
  Future<void> clear() {
    if (throwOnClear) throw Exception('очистка не удалась');
    return _inner.clear();
  }
}

/// Хранилище, которое запоминает порядок записи access и refresh — для
/// проверки риска 3 плана `10-refresh.md` (refresh пишется раньше access).
class _OrderTrackingStorage implements TokenStorage {
  _OrderTrackingStorage(this.calls);

  final List<String> calls;
  final _inner = InMemoryTokenStorage();

  @override
  Future<String?> readToken() => _inner.readToken();

  @override
  Future<void> writeToken(String token) {
    calls.add('token');
    return _inner.writeToken(token);
  }

  @override
  Future<String?> readRefreshToken() => _inner.readRefreshToken();

  @override
  Future<void> writeRefreshToken(String token) {
    calls.add('refresh');
    return _inner.writeRefreshToken(token);
  }

  @override
  Future<String?> readLastInstitutionId() => _inner.readLastInstitutionId();

  @override
  Future<void> writeLastInstitutionId(String institutionId) => _inner.writeLastInstitutionId(institutionId);

  @override
  Future<void> clear() => _inner.clear();
}

typedef _Routes = Map<String, Future<ResponseBody> Function(RequestOptions)>;

/// Фейковый бэкенд: маршрутизация по `"МЕТОД путь"`, без параметризации пути
/// — в тестах id учреждения известен заранее.
_Routes _routes(Map<String, Future<ResponseBody> Function(RequestOptions)> map) => map;

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
      // Настоящий `apiClientProvider` (Р2, ревью `10-refresh.md`): токен и
      // поколение сессии реально идут от `_TokenHolder`, подменяется только
      // транспорт — иначе тесты проверяли бы не ту привязку, что работает в
      // приложении.
      apiClientDioProvider.overrideWithValue(buildFakeDio(_dispatch(routes))),
    ],
  );
  addTearDown(container.dispose);
  // `NotifierProvider` ленивый: без первого чтения `build()` (и запуск
  // холодного старта) не выполнится вовсе, и весь `_settle()` ниже просто
  // ничего не ждёт.
  container.read(sessionProvider);
  return container;
}

/// Дать отвисеть цепочкам `Future`, запущенным в фоне (`build()` сессии не
/// ждёт `_bootstrap`, как и не ждут её реальные вызовы `ref.read`).
Future<void> _settle() async {
  for (var i = 0; i < 50; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 1));
  }
}

void main() {
  group('холодный старт', () {
    test('с живым токеном и уже верным контекстом входит и не трогает сеть автовыбором', () async {
      final institutionId = 'inst-1';
      final token = fakeJwt({
        'sub': 'u1',
        'institution_id': institutionId,
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);
      await storage.writeLastInstitutionId(institutionId);

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, [
            membershipJson(institutionId: institutionId),
          ]),
        }),
      );

      expect(container.read(sessionProvider).status, SessionStatus.loading);
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.authed);
      expect(state.institution?.id, institutionId);
    });

    test('с истёкшим токеном сразу даёт anon без обращения к серверу', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: -5))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);

      final container = _buildContainer(storage, _routes({}));

      await _settle();

      expect(container.read(sessionProvider).status, SessionStatus.anon);
      expect(await storage.readToken(), isNull);
    });
  });

  test('единственное активное членство выбирается автоматически', () async {
    final loginToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final contextToken = fakeJwt({
      'sub': 'u1',
      'institution_id': 'inst-1',
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(loginToken);

    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, [
          membershipJson(institutionId: 'inst-1'),
        ]),
        'POST /institutions/inst-1/token': (o) async => jsonResponse(200, tokenJson(contextToken)),
      }),
    );

    await _settle();

    final state = container.read(sessionProvider);
    expect(state.institution?.id, 'inst-1');
    expect(await storage.readLastInstitutionId(), 'inst-1');
  });

  test('последнее выбранное активное учреждение приоритетнее одного из нескольких', () async {
    final loginToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final contextToken = fakeJwt({
      'sub': 'u1',
      'institution_id': 'inst-2',
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });
    final storage = InMemoryTokenStorage();
    await storage.writeToken(loginToken);
    await storage.writeLastInstitutionId('inst-2');

    var wrongTargetCalled = false;
    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, [
          membershipJson(institutionId: 'inst-1'),
          membershipJson(institutionId: 'inst-2'),
        ]),
        'POST /institutions/inst-1/token': (o) async {
          wrongTargetCalled = true;
          return jsonResponse(200, tokenJson(loginToken));
        },
        'POST /institutions/inst-2/token': (o) async => jsonResponse(200, tokenJson(contextToken)),
      }),
    );

    await _settle();

    expect(wrongTargetCalled, isFalse);
    expect(container.read(sessionProvider).institution?.id, 'inst-2');
  });

  test('must_change_password приходит в user и виден в состоянии сессии', () async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);

    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson(mustChangePassword: true)),
        'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
      }),
    );

    await _settle();

    expect(container.read(sessionProvider).user?.mustChangePassword, isTrue);
  });

  test('401 во время работы сбрасывает сессию и оставляет сообщение', () async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    var membershipsCalls = 0;

    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async {
          membershipsCalls++;
          if (membershipsCalls == 1) return jsonResponse(200, <Object>[]);
          return jsonResponse(401, {'detail': 'Unauthorized'});
        },
      }),
    );

    await _settle();
    expect(container.read(sessionProvider).status, SessionStatus.authed);

    await container.read(sessionProvider.notifier).reloadMemberships();
    await _settle();

    final state = container.read(sessionProvider);
    expect(state.status, SessionStatus.anon);
    expect(state.notice, isNotNull);
  });

  test('INSTITUTION_CONTEXT_REQUIRED помечает необходимость выбора учреждения', () async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);

    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        'GET /institutions/inst-1/me/currency': (o) async =>
            jsonResponse(403, {'detail': 'INSTITUTION_CONTEXT_REQUIRED'}),
      }),
    );
    await _settle();
    expect(container.read(sessionProvider).needsInstitutionSelection, isFalse);

    final client = container.read(apiClientProvider);
    try {
      await client.request<void>('/institutions/inst-1/me/currency');
    } catch (_) {
      // Ошибка ожидаема — интересует лишь побочный эффект в сессии.
    }

    expect(container.read(sessionProvider).needsInstitutionSelection, isTrue);
  });

  test('выход при сетевой ошибке всё равно очищает хранилище', () async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);
    await storage.writeLastInstitutionId('inst-1');

    final container = _buildContainer(
      storage,
      _routes({
        'GET /users/me': (o) async => jsonResponse(200, userJson()),
        'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        'POST /users/auth/jwt/logout': (o) async {
          throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
        },
      }),
    );
    await _settle();

    await container.read(sessionProvider.notifier).logout();

    expect(container.read(sessionProvider).status, SessionStatus.anon);
    expect(await storage.readToken(), isNull);
    expect(await storage.readLastInstitutionId(), isNull);
  });

  group('гонки поколений сессии (С2)', () {
    test('logout, пока висит POST .../token: запоздавший ответ ничего не пишет', () async {
      const institutionId = 'inst-1';
      const targetId = 'inst-2';
      final initialToken = fakeJwt({
        'sub': 'u1',
        'institution_id': institutionId,
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });
      final lateToken = fakeJwt({
        'sub': 'u1',
        'institution_id': targetId,
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });
      final storage = InMemoryTokenStorage();
      await storage.writeToken(initialToken);
      await storage.writeLastInstitutionId(institutionId);

      final pendingToken = Completer<ResponseBody>();
      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, [
            membershipJson(institutionId: institutionId),
            membershipJson(institutionId: targetId),
          ]),
          'POST /institutions/inst-2/token': (o) async => pendingToken.future,
          'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
        }),
      );
      await _settle();

      final notifier = container.read(sessionProvider.notifier);
      final selectFuture = notifier.selectInstitution(targetId);

      await notifier.logout();
      expect(container.read(sessionProvider).status, SessionStatus.anon);

      // Ответ на выбор учреждения приходит уже после выхода.
      pendingToken.complete(jsonResponse(200, tokenJson(lateToken)));
      await selectFuture;
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(state.token, isNull);
      expect(container.read(apiClientProvider).tokenProvider(), isNull);
      expect(await storage.readToken(), isNull);
      expect(await storage.readLastInstitutionId(), isNull);
    });

    test('401 во время висящего выбора учреждения: запоздавший ответ ничего не пишет', () async {
      const institutionId = 'inst-1';
      const targetId = 'inst-2';
      final initialToken = fakeJwt({
        'sub': 'u1',
        'institution_id': institutionId,
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });
      final lateToken = fakeJwt({
        'sub': 'u1',
        'institution_id': targetId,
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });
      final storage = InMemoryTokenStorage();
      await storage.writeToken(initialToken);

      var membershipsCalls = 0;
      final pendingToken = Completer<ResponseBody>();
      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async {
            membershipsCalls++;
            if (membershipsCalls == 1) {
              return jsonResponse(200, [
                membershipJson(institutionId: institutionId),
                membershipJson(institutionId: targetId),
              ]);
            }
            return jsonResponse(401, {'detail': 'Unauthorized'});
          },
          'POST /institutions/inst-2/token': (o) async => pendingToken.future,
        }),
      );
      await _settle();

      final notifier = container.read(sessionProvider.notifier);
      final selectFuture = notifier.selectInstitution(targetId);

      // Другой запрос в это же время ловит 401 и сбрасывает сессию.
      await notifier.reloadMemberships();
      expect(container.read(sessionProvider).status, SessionStatus.anon);

      pendingToken.complete(jsonResponse(200, tokenJson(lateToken)));
      await selectFuture;
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(state.token, isNull);
      expect(container.read(apiClientProvider).tokenProvider(), isNull);
      expect(await storage.readToken(), isNull);
    });

    test('запоздалый список учреждений A не попадает в сессию B после перелогина', () async {
      final tokenA = fakeJwt({'sub': 'a', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(tokenA);

      final pendingA = Completer<ResponseBody>();
      var institutionsCalls = 0;
      final loginTokenB = fakeJwt({'sub': 'b', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final contextTokenB = fakeJwt({
        'sub': 'b',
        'institution_id': 'inst-b',
        'exp': unixSecondsFromNow(const Duration(minutes: 15)),
      });

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async {
            institutionsCalls++;
            if (institutionsCalls == 1) {
              // Первичная загрузка A на холодном старте — сразу пусто.
              return jsonResponse(200, <Object>[]);
            }
            if (institutionsCalls == 2) {
              // Запоздалый повтор A — ответ придёт позже, вручную.
              return pendingA.future;
            }
            // Членства B, загруженные уже после перелогина.
            return jsonResponse(200, [membershipJson(institutionId: 'inst-b')]);
          },
          'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
          'POST /users/auth/jwt/login': (o) async => jsonResponse(200, tokenJson(loginTokenB)),
          'POST /institutions/inst-b/token': (o) async => jsonResponse(200, tokenJson(contextTokenB)),
        }),
      );
      await _settle();
      expect(institutionsCalls, 1);

      final notifier = container.read(sessionProvider.notifier);
      final staleReload = notifier.reloadMemberships();

      await notifier.logout();
      await notifier.login('b@example.com', 'password');
      await _settle();

      final beforeStaleResponse = container.read(sessionProvider);
      expect(
        beforeStaleResponse.memberships?.map((m) => m.institutionId).toList(),
        ['inst-b'],
      );

      // Запоздалый ответ A приходит уже в сессии B.
      pendingA.complete(jsonResponse(200, [membershipJson(institutionId: 'inst-a-late')]));
      await staleReload;
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.memberships?.map((m) => m.institutionId).toList(), ['inst-b']);
    });
  });

  group('refresh (план 10-refresh, Ч5)', () {
    test('старт с истёкшим access и живым refresh восстанавливает сессию', () async {
      final expiredToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: -5))});
      final newAccessToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(expiredToken);
      await storage.writeRefreshToken('old-refresh');
      await storage.writeLastInstitutionId('inst-1');

      final container = _buildContainer(
        storage,
        _routes({
          'POST /users/auth/jwt/refresh': (o) async => jsonResponse(200, {
            'access_token': newAccessToken,
            'token_type': 'bearer',
            'refresh_token': 'new-refresh',
          }),
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        }),
      );

      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.authed);
      expect(state.token, newAccessToken);
      expect(await storage.readToken(), newAccessToken);
      expect(await storage.readRefreshToken(), 'new-refresh');
    });

    test('новый refresh пишется в хранилище раньше access', () async {
      final expiredToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: -5))});
      final newAccessToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final calls = <String>[];
      final storage = _OrderTrackingStorage(calls);
      await storage.writeToken(expiredToken);
      await storage.writeRefreshToken('old-refresh');
      calls.clear(); // Интересует только порядок записи во время refresh.

      _buildContainer(
        storage,
        _routes({
          'POST /users/auth/jwt/refresh': (o) async => jsonResponse(200, {
            'access_token': newAccessToken,
            'token_type': 'bearer',
            'refresh_token': 'new-refresh',
          }),
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        }),
      );

      await _settle();

      expect(calls, ['refresh', 'token']);
    });

    test('refresh отвечает 401 — сессия anon, оба токена стёрты', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);
      await storage.writeRefreshToken('old-refresh');
      await storage.writeLastInstitutionId('inst-1');

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
          'GET /protected': (o) async => jsonResponse(401, {'detail': 'Unauthorized'}),
          'POST /users/auth/jwt/refresh': (o) async =>
              jsonResponse(401, {'detail': 'REFRESH_TOKEN_INVALID'}),
        }),
      );
      await _settle();
      expect(container.read(sessionProvider).status, SessionStatus.authed);

      final client = container.read(apiClientProvider);
      try {
        await client.request<void>('/protected');
      } catch (_) {
        // Ожидаемо — интересует итоговое состояние сессии.
      }
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(await storage.readToken(), isNull);
      expect(await storage.readRefreshToken(), isNull);
    });

    test('сетевая ошибка при refresh — сессия остаётся authed, токены на месте', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);
      await storage.writeRefreshToken('old-refresh');

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
          'GET /protected': (o) async => jsonResponse(401, {'detail': 'Unauthorized'}),
          'POST /users/auth/jwt/refresh': (o) async {
            throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
          },
        }),
      );
      await _settle();

      final client = container.read(apiClientProvider);
      try {
        await client.request<void>('/protected');
      } catch (_) {
        // Ожидаемо — исходный запрос всё равно проваливается.
      }
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.authed);
      expect(await storage.readToken(), token);
      expect(await storage.readRefreshToken(), 'old-refresh');
    });

    test(
      'холодный старт с истёкшим access и параллельный 401 на другом запросе шлют один refresh на сервер',
      () async {
        // Дефект плана 10-refresh (Ч5): _bootstrap звал _performRefresh
        // напрямую, мимо single-flight ApiClient — параллельный 401 от
        // перехватчика запускал второй refresh тем же токеном, а сервер на
        // повторное предъявление вытесненного refresh-токена гасит всю
        // сессию.
        final expiredToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: -5))});
        final newAccessToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
        final storage = InMemoryTokenStorage();
        await storage.writeToken(expiredToken);
        await storage.writeRefreshToken('old-refresh');
        await storage.writeLastInstitutionId('inst-1');

        var refreshCalls = 0;
        var protectedCalls = 0;
        final pendingRefresh = Completer<ResponseBody>();
        final refreshRequested = Completer<void>();

        final container = _buildContainer(
          storage,
          _routes({
            'POST /users/auth/jwt/refresh': (o) async {
              refreshCalls++;
              if (!refreshRequested.isCompleted) refreshRequested.complete();
              return pendingRefresh.future;
            },
            'GET /users/me': (o) async => jsonResponse(200, userJson()),
            'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
            'GET /protected': (o) async {
              protectedCalls++;
              // Первый заход — протухший токен (401 запускает refresh через
              // перехватчик); повтор после обновления — уже с новым токеном.
              if (protectedCalls == 1) return jsonResponse(401, {'detail': 'Unauthorized'});
              return jsonResponse(200, {'ok': true});
            },
          }),
        );

        // Второй путь к refresh, независимый от _bootstrap: обычный 401 на
        // произвольном запросе через тот же ApiClient. Запускается сразу,
        // не дожидаясь _settle(), чтобы попасть в то же окно, что и
        // _bootstrap.
        final client = container.read(apiClientProvider);
        final protectedFuture = client.request<void>('/protected').catchError((_) {});

        await refreshRequested.future;
        pendingRefresh.complete(jsonResponse(200, {
          'access_token': newAccessToken,
          'token_type': 'bearer',
          'refresh_token': 'new-refresh',
        }));

        await protectedFuture;
        await _settle();

        expect(refreshCalls, 1);
        final state = container.read(sessionProvider);
        expect(state.status, SessionStatus.authed);
        expect(state.token, newAccessToken);
        expect(await storage.readRefreshToken(), 'new-refresh');
      },
    );

    test('logout во время refresh: результат не применяется, осиротевший refresh гасится logout, сессия anon', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final newAccessToken = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);
      await storage.writeRefreshToken('old-refresh');

      final pendingRefresh = Completer<ResponseBody>();
      final refreshRequested = Completer<void>();
      final logoutBodies = <Object?>[];
      final logoutHeaders = <Map<String, dynamic>>[];

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
          'GET /protected': (o) async => jsonResponse(401, {'detail': 'Unauthorized'}),
          'POST /users/auth/jwt/refresh': (o) async {
            if (!refreshRequested.isCompleted) refreshRequested.complete();
            return pendingRefresh.future;
          },
          'POST /users/auth/jwt/logout': (o) async {
            logoutBodies.add(o.data);
            logoutHeaders.add(o.headers);
            return jsonResponse(204, '');
          },
        }),
      );
      await _settle();

      final notifier = container.read(sessionProvider.notifier);
      final client = container.read(apiClientProvider);
      final protectedFuture = client.request<void>('/protected').catchError((_) {});

      // Дожидаемся, что refresh-запрос действительно ушёл на сервер (а не
      // просто запланирован), прежде чем гнать logout — иначе порядок двух
      // независимых цепочек `Future` не гарантирован.
      await refreshRequested.future;

      await notifier.logout();
      expect(container.read(sessionProvider).status, SessionStatus.anon);

      // Ответ на refresh приходит уже после выхода — с новым refresh-токеном,
      // который эта сессия больше не признаёт своим.
      pendingRefresh.complete(jsonResponse(200, {
        'access_token': newAccessToken,
        'token_type': 'bearer',
        'refresh_token': 'orphan-refresh',
      }));
      await protectedFuture;
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(await storage.readToken(), isNull);
      expect(await storage.readRefreshToken(), isNull);
      // Один logout — от явного выхода пользователя (старый refresh), второй
      // — best-effort гашение осиротевшего нового refresh.
      expect(logoutBodies.length, 2);
      expect((logoutBodies[0] as Map)['refresh_token'], 'old-refresh');
      expect((logoutBodies[1] as Map)['refresh_token'], 'orphan-refresh');
      // Р3, ревью 10-refresh: явный выход пользователя шлёт Bearer своей же
      // сессии, а best-effort гашение осиротевшего refresh — нет, чтобы не
      // отзывать access текущей (уже другой) сессии.
      expect(logoutHeaders[0]['Authorization'], 'Bearer $token');
      expect(logoutHeaders[0]['X-Client'], 'mobile');
      expect(logoutHeaders[1].containsKey('Authorization'), isFalse);
      expect(logoutHeaders[1]['X-Client'], 'mobile');
    });

    test(
      'logout и новый вход во время висящего refresh: запоздалый 401 старой сессии не гасит новую и не '
      'стирает её хранилище (К6, ревью 10-refresh)',
      () async {
        final tokenA = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
        final loginTokenB = fakeJwt({'sub': 'b', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
        final storage = InMemoryTokenStorage();
        await storage.writeToken(tokenA);
        await storage.writeRefreshToken('old-refresh');

        final pendingRefresh = Completer<ResponseBody>();
        final refreshRequested = Completer<void>();

        final container = _buildContainer(
          storage,
          _routes({
            'GET /users/me': (o) async => jsonResponse(200, userJson()),
            'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
            'GET /protected': (o) async => jsonResponse(401, {'detail': 'Unauthorized'}),
            'POST /users/auth/jwt/refresh': (o) async {
              if (!refreshRequested.isCompleted) refreshRequested.complete();
              return pendingRefresh.future;
            },
            'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
            'POST /users/auth/jwt/login': (o) async => jsonResponse(200, {
              'access_token': loginTokenB,
              'token_type': 'bearer',
              'refresh_token': 'new-refresh-b',
            }),
          }),
        );
        await _settle();

        final notifier = container.read(sessionProvider.notifier);
        final client = container.read(apiClientProvider);
        final protectedFuture = client.request<void>('/protected').catchError((_) {});

        // Дожидаемся, что refresh старой сессии (A) действительно ушёл на
        // сервер, прежде чем гнать logout и новый вход.
        await refreshRequested.future;

        await notifier.logout();
        await notifier.login('b@example.com', 'password');
        await _settle();

        expect(container.read(sessionProvider).status, SessionStatus.authed);
        expect(container.read(sessionProvider).token, loginTokenB);

        // Запоздалый ответ на refresh A — настоящий 401 от сервера, а не
        // сетевой сбой.
        pendingRefresh.complete(jsonResponse(401, {'detail': 'REFRESH_TOKEN_INVALID'}));
        await protectedFuture;
        await _settle();

        final state = container.read(sessionProvider);
        expect(state.status, SessionStatus.authed);
        expect(state.token, loginTokenB);
        expect(await storage.readToken(), loginTokenB);
        expect(await storage.readRefreshToken(), 'new-refresh-b');
      },
    );
  });

  group('метка поколения на запросе (Р2, ревью 10-refresh)', () {
    test(
      'запрос X получает 401 после logout X и входа Y: без refresh, без повтора, сессия Y цела',
      () async {
        final tokenX = fakeJwt({'sub': 'x', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
        final loginTokenY = fakeJwt({'sub': 'y', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
        final storage = InMemoryTokenStorage();
        await storage.writeToken(tokenX);

        final pendingProtected = Completer<ResponseBody>();
        final protectedRequested = Completer<void>();
        var refreshCalls = 0;

        final container = _buildContainer(
          storage,
          _routes({
            'GET /users/me': (o) async => jsonResponse(200, userJson()),
            'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
            'GET /protected': (o) async {
              if (!protectedRequested.isCompleted) protectedRequested.complete();
              return pendingProtected.future;
            },
            'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
            'POST /users/auth/jwt/login': (o) async => jsonResponse(200, {
              'access_token': loginTokenY,
              'token_type': 'bearer',
              'refresh_token': 'refresh-y',
            }),
            'POST /users/auth/jwt/refresh': (o) async {
              refreshCalls++;
              throw StateError('обновление не должно запускаться для чужого поколения');
            },
          }),
        );
        await _settle();

        final notifier = container.read(sessionProvider.notifier);
        final client = container.read(apiClientProvider);
        final protectedFuture = client.request<void>('/protected');

        // Запрос X действительно ушёл, прежде чем X выходит, а Y входит.
        await protectedRequested.future;

        await notifier.logout();
        await notifier.login('y@example.com', 'password');
        await _settle();

        final afterLogin = container.read(sessionProvider);
        expect(afterLogin.status, SessionStatus.authed);
        expect(afterLogin.token, loginTokenY);

        // 401 запроса X приходит уже в сессии Y.
        pendingProtected.complete(jsonResponse(401, {'detail': 'Unauthorized'}));

        await expectLater(
          protectedFuture,
          throwsA(isA<ApiError>().having((e) => e.status, 'status', 401)),
        );
        await _settle();

        expect(refreshCalls, 0);
        final state = container.read(sessionProvider);
        expect(state.status, SessionStatus.authed);
        expect(state.token, loginTokenY);
        expect(await storage.readToken(), loginTokenY);
        expect(container.read(apiClientProvider).tokenProvider(), loginTokenY);
      },
    );
  });

  group('старт без сети (Н4/Н5/открытый вопрос Ч3)', () {
    test('живой токен и сетевая ошибка getMe: токен остаётся, статус loading с ошибкой, повтор даёт authed', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);

      var shouldFail = true;
      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async {
            if (shouldFail) {
              throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
            }
            return jsonResponse(200, userJson());
          },
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
        }),
      );
      await _settle();

      var state = container.read(sessionProvider);
      expect(state.status, SessionStatus.loading);
      expect(state.startupError, isNotNull);
      expect(await storage.readToken(), token);

      shouldFail = false;
      await container.read(sessionProvider.notifier).retryStart();
      await _settle();

      state = container.read(sessionProvider);
      expect(state.status, SessionStatus.authed);
      expect(state.startupError, isNull);
    });

    test('старт с сетевой ошибкой: токен истёк к моменту повтора — anon и пустое хранилище', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(seconds: 1))});
      final storage = InMemoryTokenStorage();
      await storage.writeToken(token);

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async {
            throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
          },
        }),
      );
      await _settle();
      expect(container.read(sessionProvider).status, SessionStatus.loading);
      expect(container.read(sessionProvider).startupError, isNotNull);

      await Future<void>.delayed(const Duration(milliseconds: 1200));
      await container.read(sessionProvider.notifier).retryStart();
      await _settle();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(await storage.readToken(), isNull);
    });

    test('readToken бросает исключение — старт даёт anon', () async {
      final storage = _ThrowingStorage(throwOnRead: true);

      final container = _buildContainer(storage, _routes({}));
      await _settle();

      expect(container.read(sessionProvider).status, SessionStatus.anon);
    });

    test('clear() бросает при выходе — выход всё равно завершается', () async {
      final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      final storage = _ThrowingStorage(throwOnClear: true);
      await storage.writeToken(token);

      final container = _buildContainer(
        storage,
        _routes({
          'GET /users/me': (o) async => jsonResponse(200, userJson()),
          'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
          'POST /users/auth/jwt/logout': (o) async => jsonResponse(204, ''),
        }),
      );
      await _settle();
      expect(container.read(sessionProvider).status, SessionStatus.authed);

      await container.read(sessionProvider.notifier).logout();

      final state = container.read(sessionProvider);
      expect(state.status, SessionStatus.anon);
      expect(container.read(apiClientProvider).tokenProvider(), isNull);
    });
  });
}
