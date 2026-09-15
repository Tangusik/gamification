/// Транспорт до API поверх `dio`.
///
/// База — `--dart-define=API_BASE_URL`, без завершающего слэша (правило
/// перенесено из `services/web/src/api/client.ts`: FastAPI отвечает 307 на
/// путь со слэшем, и через шлюз это битый адрес). Значение приходит извне —
/// у эмулятора и телефона разные адреса (`.claude/plans/09-mobile-app.md`,
/// раздел 4), и клиент их не выбирает сам.
///
/// Токен клиент не хранит — только запрашивает его перед каждым запросом
/// через [TokenProvider]. Само хранилище токена — задача Ч3
/// (`flutter_secure_storage`), здесь достаточно колбэка.
library;

import 'dart:async';

import 'package:dio/dio.dart';

import 'errors.dart';

/// Базовый адрес API. Пример: `http://10.0.2.2:8080/api/v1` для эмулятора.
const String apiBaseUrl = String.fromEnvironment('API_BASE_URL');

/// Потолок ожидания ответа — с запасом к самому долгому запросу этапа (вход,
/// где сервер считает Argon2), но заметно меньше терпения пользователя.
const Duration requestTimeout = Duration(seconds: 15);

/// Текущий access-токен или `null`, если пользователь анонимен. Хранилище
/// подключает Ч3; здесь — только точка чтения перед каждым запросом.
typedef TokenProvider = String? Function();

/// Обновить access-токен по протухшему запросу (план `10-refresh.md`, Ч5) и
/// вернуть новый. Подключает `SessionNotifier`: он же решает, что делать с
/// результатом (поколение сессии, порядок записи в хранилище). Бросает
/// исключение, если обновиться не удалось — по любой причине, включая сеть.
typedef TokenRefresher = Future<String> Function();

/// Текущее поколение сессии (Р2, ревью `10-refresh.md`) — растёт при logout,
/// 401 и новом входе (`SessionNotifier._generation`). По умолчанию `() => 0`:
/// клиенты, которых сессия не подключает (например, тесты `client_test.dart`
/// без `SessionNotifier`), ведут себя как раньше — все запросы одного
/// поколения, метка ничего не меняет.
typedef SessionGenerationProvider = int Function();

/// Реакции на ошибки, общие для всего приложения — подключаются Ч3 к сессии
/// и навигации (`go_router`). Сама навигация сюда не входит.
class ApiErrorHandlers {
  const ApiErrorHandlers({this.onUnauthorized, this.onInstitutionContextRequired});

  /// 401: токена нет или он погашен — чистим сессию.
  final void Function()? onUnauthorized;

  /// 403 `INSTITUTION_CONTEXT_REQUIRED`: нужен выбор учреждения.
  final void Function()? onInstitutionContextRequired;
}

/// Единственное место, где ответ или ошибка сети превращаются в [ApiError].
///
/// Ветвление по HTTP-статусу, а не по тексту `detail`: 401 сегодня приходит
/// со строкой `Unauthorized` в теле, но клиент от смены текста не сломается.
class ApiClient {
  ApiClient({
    required this.tokenProvider,
    Dio? dio,
    this.sessionGeneration = _defaultGeneration,
  }) : _dio = dio ??
            Dio(
              BaseOptions(
                baseUrl: apiBaseUrl,
                connectTimeout: requestTimeout,
                sendTimeout: requestTimeout,
                receiveTimeout: requestTimeout,
                // Успех — только 2xx; остальное разбирается в request()
                // через DioException, как единая точка превращения в ApiError.
                validateStatus: (status) => status != null && status >= 200 && status < 300,
              ),
            ) {
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          if (options.extra[skipAuthExtraKey] != true) {
            final token = tokenProvider();
            if (token != null) {
              options.headers['Authorization'] = 'Bearer $token';
            }
          }
          // Метка поколения ставится вместе с токеном, в один момент (Р2).
          options.extra[_generationKey] = sessionGeneration();
          handler.next(options);
        },
        onError: _onError,
      ),
    );
  }

  static int _defaultGeneration() => 0;

  final TokenProvider tokenProvider;

  /// См. [SessionGenerationProvider].
  final SessionGenerationProvider sessionGeneration;
  final Dio _dio;

  /// Реакции на 401 и `INSTITUTION_CONTEXT_REQUIRED`. Мутируемое поле, а не
  /// конструктор: Ч3 подключает их позже, когда появляются сессия и роутер.
  ApiErrorHandlers handlers = const ApiErrorHandlers();

  /// Обновление access-токена при 401 (план `10-refresh.md`). `null` (по
  /// умолчанию) — старое поведение: 401 сразу уходит в `onUnauthorized`, без
  /// попытки обновиться. Подключает `SessionNotifier`.
  TokenRefresher? tokenRefresher;

  /// Пути, для которых 401 не запускает обновление и повтор: сам вход,
  /// обновление и выход не должны пытаться обновиться сами через себя.
  static const _noRefreshPathPrefix = '/users/auth/jwt/';

  /// Метка в `RequestOptions.extra`, что запрос уже был повторён один раз
  /// после обновления токена — защита от зацикливания, если новый токен
  /// снова получает 401.
  static const _retriedKey = 'gamification_retried_after_refresh';

  /// Метка в `RequestOptions.extra` (К5, ревью `10-refresh.md`): исходный
  /// запрос, чья ошибка на самом деле пришла с сервера через сам refresh
  /// (см. `_onError`), уже разобран в `_performRefresh` — второй `_notify`
  /// по нему не нужен и опасен (запоздалая сессия может быть уже другой).
  static const _skipNotifyKey = 'gamification_skip_notify';

  /// Метка в `RequestOptions.extra` (Р2, ревью `10-refresh.md`): поколение
  /// сессии на момент отправки запроса — см. [SessionGenerationProvider].
  static const _generationKey = 'gamification_session_generation';

  /// Метка в `Options.extra` (Р3, ревью `10-refresh.md`): запрос не должен
  /// получать `Authorization` текущей сессии — например, best-effort logout
  /// осиротевшего refresh-токена, которому чужой Bearer только отзовёт
  /// доступ текущей, другой, сессии.
  static const skipAuthExtraKey = 'gamification_skip_auth';

  /// Один общий `Completer` на клиент: параллельные 401 ждут один и тот же
  /// вызов обновления, а не запускают его каждый сам по себе (иначе два
  /// одновременных refresh одним токеном гасят всю сессию — план
  /// `10-refresh.md`, критично).
  Completer<String>? _refreshInFlight;

  /// Пауза перед единственным повтором обновления токена после сетевого
  /// сбоя без ответа сервера (К3, ревью `10-refresh.md`). Мутируемое поле, а
  /// не константа — тесты подставляют `Duration.zero`, чтобы не ждать 1.5 с
  /// по-настоящему.
  Duration refreshRetryDelay = const Duration(milliseconds: 1500);

  /// Единая точка входа в single-flight обновления токена — используется и
  /// перехватчиком `_onError`, и холодным стартом сессии (`_bootstrap`), чтобы
  /// два независимых пути никогда не запускали обновление одновременно
  /// (план `10-refresh.md`, Ч5).
  Future<String> refreshAccessToken() {
    final refresher = tokenRefresher;
    if (refresher == null) {
      throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
    }
    return _refreshOnce(refresher);
  }

  Future<String> _refreshOnce(TokenRefresher refresher) {
    final pending = _refreshInFlight;
    if (pending != null) return pending.future;
    final completer = Completer<String>();
    _refreshInFlight = completer;
    Future<void>(() async {
      try {
        completer.complete(await _refreshWithRetry(refresher));
      } catch (error, stackTrace) {
        completer.completeError(error, stackTrace);
      } finally {
        _refreshInFlight = null;
      }
    });
    return completer.future;
  }

  /// Ровно один повтор обновления токена, только если сбой был без ответа
  /// сервера (К3): `refresher()` (через `_performRefresh` → `auth_api.refresh`
  /// → `request()`) сводит сетевой сбой к `ApiError(0, networkError)` — это и
  /// есть сигнал «сервер не ответил». Настоящий ответ сервера (401, 403,
  /// 5xx — любой статус, кроме 0) вторым запросом тем же токеном не
  /// исправить, поэтому такие ошибки уходят наверх сразу.
  Future<String> _refreshWithRetry(TokenRefresher refresher) async {
    try {
      return await refresher();
    } on ApiError catch (error) {
      if (error.status != 0) rethrow;
      await Future<void>.delayed(refreshRetryDelay);
      return refresher();
    }
  }

  Future<void> _onError(DioException error, ErrorInterceptorHandler handler) async {
    final refresher = tokenRefresher;
    final options = error.requestOptions;
    final isAuthPath = options.path.startsWith(_noRefreshPathPrefix);
    final alreadyRetried = options.extra[_retriedKey] == true;

    if (error.response?.statusCode == 401 && !isAuthPath && _isStaleGeneration(options)) {
      // Р2: запрос (исходный или уже повторённый после обновления — метка
      // поколения ставится в onRequest на каждый заход, включая
      // `_dio.fetch(options)` ниже) ушёл в сессии, которой уже нет (logout и
      // следующий вход обогнали её 401). Сверка стоит до `alreadyRetried` и
      // `refresher`: иначе именно повтор, догоняющий уже другую (следующую)
      // сессию, проходит мимо проверки и гасит её. Обновлять токен нечем —
      // refresh-токен либо принадлежит старой сессии, либо уже другому
      // пользователю, — а гасить текущую (возможно, чужую) сессию по этому
      // 401 нельзя. Исходная ошибка уходит вызывающему как есть, без
      // второго `_notify` (тот же флаг, что и К5/К6).
      options.extra[_skipNotifyKey] = true;
      handler.next(error);
      return;
    }

    if (error.response?.statusCode == 401 && !isAuthPath && !alreadyRetried && refresher != null) {
      final String token;
      try {
        token = await refreshAccessToken();
      } catch (error) {
        // Обновление не удалось. Реакция на сессию уже случилась внутри
        // refresher (настоящий 401 от сервера гасит сессию через
        // `_performRefresh`, с проверкой поколения — К6; смена поколения —
        // через best-effort logout осиротевшего токена). Исходному запросу
        // остаётся различить две причины (К5): настоящий отказ сервера
        // (`ApiError` со статусом 401) — своей отличимой ошибкой, без
        // повторного `_notify`; сетевой сбой — как и раньше, сетевой
        // ошибкой.
        if (error is ApiError && error.status == 401) {
          options.extra[_skipNotifyKey] = true;
          handler.reject(
            DioException(
              requestOptions: options,
              type: DioExceptionType.badResponse,
              response: Response<Object?>(
                requestOptions: options,
                statusCode: 401,
                data: {'detail': error.code},
              ),
            ),
          );
        } else {
          handler.reject(
            DioException(requestOptions: options, type: DioExceptionType.connectionError),
          );
        }
        return;
      }

      // Метка стоит до повтора: если новый токен снова получит 401, второй
      // заход сюда должен пойти обычным путём (onUnauthorized), а не
      // запускать обновление по кругу.
      options.extra[_retriedKey] = true;
      options.headers['Authorization'] = 'Bearer $token';
      try {
        final retried = await _dio.fetch<Object?>(options);
        handler.resolve(retried);
      } on DioException catch (retryError) {
        handler.next(retryError);
      }
      return;
    }
    handler.next(error);
  }

  /// Метка поколения на запросе (см. [_generationKey]) не совпадает с
  /// текущим — запрос отправлен уже закрытой сессией.
  bool _isStaleGeneration(RequestOptions options) {
    final tagged = options.extra[_generationKey];
    return tagged is int && tagged != sessionGeneration();
  }

  /// Выполнить запрос к API и вернуть разобранное тело.
  ///
  /// `T` — ожидаемая форма JSON (`Map<String, dynamic>` или
  /// `List<dynamic>`); для 204 результата нет, вызывающий код указывает
  /// `T = void`.
  Future<T> request<T>(
    String path, {
    String method = 'GET',
    Object? json,
    Map<String, String>? form,
    Map<String, String>? headers,
    Map<String, dynamic>? extra,
  }) async {
    try {
      final options = Options(
        method: method,
        contentType: form != null ? Headers.formUrlEncodedContentType : null,
        headers: headers,
        extra: extra,
      );
      final response = await _dio.request<Object?>(
        path,
        data: form ?? json,
        options: options,
      );
      if (response.statusCode == 204) {
        return null as T;
      }
      return response.data as T;
    } on DioException catch (error) {
      final apiError = _asApiError(error);
      if (!_shouldSkipNotify(error)) {
        _notify(apiError);
      }
      throw apiError;
    }
  }

  /// Запросы к самому refresh (К6) и ошибки, уже разобранные `_onError` за
  /// исходный запрос (К5), не должны запускать `_notify` второй раз —
  /// реакция на сессию (или её отсутствие из-за смены поколения) уже
  /// случилась там, где сессия умеет сверяться со своим поколением.
  bool _shouldSkipNotify(DioException error) {
    final options = error.requestOptions;
    if (options.path.startsWith(_noRefreshPathPrefix)) return true;
    return options.extra[_skipNotifyKey] == true;
  }

  void _notify(ApiError error) {
    if (error.status == 401) {
      handlers.onUnauthorized?.call();
    } else if (error.status == 403 && error.code == institutionContextRequired) {
      handlers.onInstitutionContextRequired?.call();
    }
  }

  /// Свести любую ошибку `dio` к [ApiError].
  ///
  /// Отсутствие ответа покрывает сеть, отмену и таймаут разом — ровно то,
  /// на что клиент реагирует одинаково: [networkError].
  ApiError _asApiError(DioException error) {
    final response = error.response;
    if (response == null) {
      return const ApiError(0, networkError);
    }
    return toApiError(response.statusCode ?? 0, response.data);
  }
}
