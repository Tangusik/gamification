/// Сессия и контекст учреждения — зеркало
/// `services/web/src/auth/AuthProvider.tsx` и `authContext.ts` на Riverpod
/// (`Notifier`, решение В3 плана `09-mobile-app.md`, без кодогенерации).
///
/// Состояние — `loading/anon/authed`, как в вебе: `loading` держится, пока
/// сохранённый токен ещё не проверен, и в это время приложение не шлёт
/// запросов (`06-identity-and-tokens.md`).
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/auth_api.dart' as auth_api;
import '../api/client.dart';
import '../api/errors.dart';
import '../i18n/error_messages.dart';
import 'claims.dart';
import 'token_storage.dart';

/// Статус сессии.
enum SessionStatus { loading, anon, authed }

/// Активное учреждение: id — из claim токена, роль и название — из свежего
/// `GET /institutions` (claim может отставать от него до 900 с).
class InstitutionContext {
  const InstitutionContext({required this.id, required this.role, required this.name, required this.currencyName});

  final String id;
  final auth_api.UserRole role;
  final String name;

  /// Название внутренней валюты учреждения; `null`, пока не задано.
  final String? currencyName;

  @override
  bool operator ==(Object other) =>
      other is InstitutionContext &&
      other.id == id &&
      other.role == role &&
      other.name == name &&
      other.currencyName == currencyName;

  @override
  int get hashCode => Object.hash(id, role, name, currencyName);
}

/// Сентинел для необязательных именованных параметров `copyWith`, которым
/// нужно уметь явно сбросить значение в `null`.
const Object _unset = Object();

class SessionState {
  const SessionState({
    this.status = SessionStatus.loading,
    this.token,
    this.user,
    this.memberships,
    this.membershipsError,
    this.institution,
    this.needsInstitutionSelection = false,
    this.notice,
    this.startupError,
  });

  final SessionStatus status;

  /// Текущий токен; нужен вызовам API от имени пользователя.
  final String? token;
  final auth_api.User? user;

  /// Собственные членства, включая неактивные; `null` до первой загрузки.
  final List<auth_api.Membership>? memberships;
  final Object? membershipsError;

  /// Активное учреждение, полученное из токена и списка членств.
  final InstitutionContext? institution;

  /// `true` после 403 `INSTITUTION_CONTEXT_REQUIRED` — уводит на выбор
  /// учреждения, пока не будет сделан явный выбор.
  final bool needsInstitutionSelection;

  /// Сообщение для экрана входа, например «сессия истекла» после 401.
  final String? notice;

  /// Ошибка холодного старта (`_bootstrap`) при живом токене: сеть, таймаут,
  /// 5xx или нечитаемый ответ. Заполняется только при `status == loading` —
  /// экран ожидания сессии показывает «Повторить» вместо вечной загрузки.
  final Object? startupError;

  SessionState copyWith({
    SessionStatus? status,
    Object? token = _unset,
    Object? user = _unset,
    Object? memberships = _unset,
    Object? membershipsError = _unset,
    Object? institution = _unset,
    bool? needsInstitutionSelection,
    Object? notice = _unset,
    Object? startupError = _unset,
  }) {
    return SessionState(
      status: status ?? this.status,
      token: identical(token, _unset) ? this.token : token as String?,
      user: identical(user, _unset) ? this.user : user as auth_api.User?,
      memberships:
          identical(memberships, _unset) ? this.memberships : memberships as List<auth_api.Membership>?,
      membershipsError: identical(membershipsError, _unset) ? this.membershipsError : membershipsError,
      institution: identical(institution, _unset) ? this.institution : institution as InstitutionContext?,
      needsInstitutionSelection: needsInstitutionSelection ?? this.needsInstitutionSelection,
      notice: identical(notice, _unset) ? this.notice : notice as String?,
      startupError: identical(startupError, _unset) ? this.startupError : startupError,
    );
  }
}

/// Держатель токена в памяти — [ApiClient.tokenProvider] синхронный, а
/// хранилище асинхронное, поэтому токен для запросов читается отсюда, а не
/// из [TokenStorage]. Обновляется синхронно с `SessionState.token`.
class _TokenHolder {
  String? value;

  /// Поколение сессии (Р2, ревью `10-refresh.md`) — живёт здесь, а не в
  /// `SessionNotifier`, по той же причине, что и токен: `apiClientProvider`
  /// создаётся раньше нотифаера и должен читать актуальное значение
  /// синхронно. `SessionNotifier._generation` — тонкий геттер/сеттер поверх
  /// этого поля, второго счётчика нет.
  int generation = 0;
}

final _tokenHolderProvider = Provider<_TokenHolder>((ref) => _TokenHolder());

/// Хранилище токена — по умолчанию `flutter_secure_storage`, в тестах
/// переопределяется на [InMemoryTokenStorage].
final tokenStorageProvider = Provider<TokenStorage>((ref) => SecureTokenStorage());

/// Транспорт для [apiClientProvider] — `null` (по умолчанию) даёт настоящий
/// `Dio` на `apiBaseUrl`. Тесты подменяют на `Dio` с фейковым адаптером, не
/// теряя при этом реальную привязку токена и поколения к [_TokenHolder]:
/// иначе тестировалась бы не та привязка, что работает в приложении (Р2,
/// ревью `10-refresh.md`).
final apiClientDioProvider = Provider<Dio?>((ref) => null);

/// Клиент API. Токен и поколение сессии передаются синхронными колбэками из
/// [_tokenHolderProvider] — держатель не пересоздаёт клиент при каждом
/// изменении сессии.
final apiClientProvider = Provider<ApiClient>((ref) {
  final holder = ref.read(_tokenHolderProvider);
  return ApiClient(
    tokenProvider: () => holder.value,
    sessionGeneration: () => holder.generation,
    dio: ref.read(apiClientDioProvider),
  );
});

final sessionProvider = NotifierProvider<SessionNotifier, SessionState>(SessionNotifier.new);

class SessionNotifier extends Notifier<SessionState> {
  @override
  SessionState build() {
    _client.handlers = ApiErrorHandlers(
      onUnauthorized: _onUnauthorized,
      onInstitutionContextRequired: _onInstitutionContextRequired,
    );
    // Обновление access-токена по протухшему запросу (план `10-refresh.md`,
    // Ч5) — единственная точка входа что для `ApiClient`, что для холодного
    // старта с истёкшим access (`_bootstrap`).
    _client.tokenRefresher = _performRefresh;
    // Холодный старт: проверка сохранённого токена — асинхронная, поэтому
    // стартовое состояние всегда `loading`, пока она не завершится.
    unawaited(_bootstrap());
    return const SessionState();
  }

  TokenStorage get _storage => ref.read(tokenStorageProvider);
  ApiClient get _client => ref.read(apiClientProvider);

  /// Счётчик поколения сессии (С2, ревью Ч6). Растёт в [_forgetSession],
  /// [_onUnauthorized] и [_applyToken] — везде, где начинается или кончается
  /// сессия. Асинхронные операции запоминают поколение в начале и сверяются
  /// с ним после каждого `await`: если оно сменилось, значит logout, 401 или
  /// новый вход обогнали ответ, и писать хранилище, токен в памяти или
  /// состояние больше нельзя — они принадлежат уже неактуальной сессии.
  ///
  /// Хранится в [_TokenHolder] (Р2, ревью `10-refresh.md`), а не в отдельном
  /// поле, — единственный источник, который синхронно читает и `ApiClient`
  /// через [apiClientProvider], и `SessionNotifier` через это геттер/сеттер.
  int get _generation => ref.read(_tokenHolderProvider).generation;
  set _generation(int value) => ref.read(_tokenHolderProvider).generation = value;

  bool _isCurrent(int generation) => ref.mounted && generation == _generation;

  void _setToken(String? token) {
    ref.read(_tokenHolderProvider).value = token;
  }

  /// Очистить хранилище токена, не давая исключению уйти наружу (Н4/Н5):
  /// это best-effort шаг, а не условие для смены состояния.
  Future<void> _clearStorageBestEffort() async {
    try {
      await _storage.clear();
    } catch (_) {
      // Хранилище недоступно — состояние сессии от этого зависеть не должно.
    }
  }

  Future<void> _bootstrap() async {
    final generation = _generation;
    String? stored;
    try {
      stored = await _storage.readToken();
    } catch (_) {
      // Н4: чтение стояло вне try — PlatformException оставлял вечный
      // loading. Хранилище чистим best-effort и уходим в anon.
      if (!_isCurrent(generation)) return;
      await _clearStorageBestEffort();
      if (!_isCurrent(generation)) return;
      _setToken(null);
      state = const SessionState(status: SessionStatus.anon);
      return;
    }
    if (!_isCurrent(generation)) return;

    if (stored == null) {
      _setToken(null);
      state = const SessionState(status: SessionStatus.anon);
      return;
    }

    if (isExpired(stored)) {
      // Истёкший по exp access — прежде чем сдаваться, пробуем обновиться по
      // живому refresh (план `10-refresh.md`, п. 5): access мог истечь,
      // пока приложение было закрыто, а refresh живёт неделями.
      final refreshTokenValue = await _storage.readRefreshToken();
      if (!_isCurrent(generation)) return;

      if (refreshTokenValue == null) {
        // Данные без refresh-токена (например, старая версия 09a) — как
        // раньше: анонимно, без обращения к серверу.
        await _clearStorageBestEffort();
        if (!_isCurrent(generation)) return;
        _setToken(null);
        state = const SessionState(status: SessionStatus.anon);
        return;
      }

      try {
        // Через single-flight клиента (не напрямую _performRefresh): холодный
        // старт и перехватчик 401 не должны запускать обновление одним и тем
        // же refresh-токеном параллельно (план `10-refresh.md`, Ч5) — сервер
        // гасит всю сессию, если вытесненный refresh-токен предъявлен снова.
        final newAccessToken = await _client.refreshAccessToken();
        if (!_isCurrent(generation)) return;
        await _finishBootstrap(newAccessToken, generation);
      } catch (error) {
        // Настоящий 401 от сервера уже увёл сессию в anon и поколение вперёд
        // внутри _performRefresh (через onUnauthorized) — проверка выше уже
        // отсекла этот случай. Сюда доходят практически только сеть, таймаут
        // и подобное: токен не трогаем, остаёмся в loading с «Повторить».
        if (!_isCurrent(generation)) return;
        state = SessionState(status: SessionStatus.loading, token: stored, startupError: error);
      }
      return;
    }

    await _finishBootstrap(stored, generation);
  }

  /// Общий хвост холодного старта для валидного access-токена — как уже
  /// сохранённого, так и только что полученного через `_performRefresh`.
  Future<void> _finishBootstrap(String token, int generation) async {
    _setToken(token);
    try {
      final user = await auth_api.getMe(_client);
      if (!_isCurrent(generation)) return;
      state = SessionState(status: SessionStatus.authed, token: token, user: user);
      unawaited(_loadMemberships());
    } catch (error) {
      // 401 уже обработан через onUnauthorized — он вызывается синхронно до
      // того, как исключение дойдёт сюда, и уже увеличил поколение, так что
      // проверка ниже отсекает этот случай сама. Сюда попадают только сеть,
      // таймаут, 5xx и нечитаемый ответ — токен не трогаем, в authed без
      // user не переходим, остаёмся в loading с ошибкой старта.
      if (!_isCurrent(generation)) return;
      state = SessionState(status: SessionStatus.loading, token: token, startupError: error);
    }
  }

  /// Повтор холодного старта после ошибки в [_bootstrap] — «Повторить» на
  /// экране ожидания сессии (`AuthPendingScreen`).
  Future<void> retryStart() async {
    if (state.status != SessionStatus.loading || state.startupError == null) return;
    state = state.copyWith(startupError: null);
    await _bootstrap();
  }

  /// 401: токена больше нет — сбрасываем сессию и показываем сообщение на
  /// экране входа. Само хранилище чистится best-effort, не блокируя реакцию.
  void _onUnauthorized() {
    _generation++;
    _setToken(null);
    state = SessionState(status: SessionStatus.anon, notice: messageForCode('AUTH_REQUIRED'));
    unawaited(_clearStorageBestEffort());
  }

  /// 403 `INSTITUTION_CONTEXT_REQUIRED`: нужен явный выбор учреждения.
  void _onInstitutionContextRequired() {
    state = state.copyWith(needsInstitutionSelection: true);
  }

  /// Выход безусловен (Н5): память и состояние обнуляются синхронно и сразу,
  /// хранилище чистится следом best-effort — ошибка `clear()` не должна
  /// оставлять пользователя в `authed`.
  Future<void> _forgetSession() async {
    _generation++;
    _setToken(null);
    state = const SessionState(status: SessionStatus.anon);
    await _clearStorageBestEffort();
  }

  /// Вход.
  Future<void> login(String email, String password) async {
    final response = await auth_api.login(_client, email: email, password: password);
    await _applyToken(response.accessToken, refreshToken: response.refreshToken);
  }

  /// Регистрация не выдаёт токен, поэтому сразу входим тем же паролем.
  Future<void> register(String email, String password) async {
    await auth_api.register(_client, email: email, password: password);
    final response = await auth_api.login(_client, email: email, password: password);
    await _applyToken(response.accessToken, refreshToken: response.refreshToken);
  }

  /// Выход безусловен: локальная часть выполняется всегда, даже если запрос
  /// на сервер не дошёл (нет сети).
  Future<void> logout() async {
    try {
      final refreshTokenValue = await _storage.readRefreshToken();
      await auth_api.logout(_client, refreshToken: refreshTokenValue);
    } catch (_) {
      // Локальный выход не имеет права зависеть от сети.
    } finally {
      await _forgetSession();
    }
  }

  /// Обновить пару токенов по refresh-токену (план `10-refresh.md`, Ч5).
  ///
  /// Подключается в [_client] как `tokenRefresher` и используется как из
  /// перехватчика `ApiClient` (401 на обычном запросе), так и из
  /// [_bootstrap] (истёкший по `exp` access при живом refresh). Поколение
  /// сессии этот метод не повышает: обновление не начинает новую сессию, оно
  /// продолжает текущую — если та ещё жива к моменту ответа.
  Future<String> _performRefresh() async {
    final generation = _generation;
    final refreshTokenValue = await _storage.readRefreshToken();

    if (refreshTokenValue == null) {
      // Нечем обновляться — эквивалентно невалидному refresh: гасим сессию
      // тем же путём, что и обычный 401. Если поколение уже сменилось (logout
      // обогнал это чтение), сессия уже погашена сама — второй раз не нужно.
      if (_isCurrent(generation)) _onUnauthorized();
      throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
    }

    final institutionId = state.institution?.id ?? await _storage.readLastInstitutionId();
    final auth_api.TokenResponse response;
    try {
      response = await auth_api.refresh(
        _client,
        refreshToken: refreshTokenValue,
        institutionId: institutionId,
      );
    } on ApiError catch (error) {
      // Настоящий 401 от самого refresh-запроса (К6, ревью `10-refresh.md`):
      // `request()` больше не гасит сессию сам через глобальный `_notify` —
      // путь `/users/auth/jwt/*` из него исключён (`_shouldSkipNotify` в
      // `client.dart`), потому что тот не сверяет поколение. Здесь сверка
      // есть: запоздалый 401 старой сессии (после logout и нового входа) не
      // должен гасить уже другую, текущую.
      if (error.status == 401 && _isCurrent(generation)) _onUnauthorized();
      rethrow;
    }
    final newRefreshToken = response.refreshToken;

    // Поколение могло смениться, пока ответ был в пути (logout, повторный
    // вход обогнали refresh). Новый результат — чужой для текущей сессии:
    // не пишем его никуда, а осиротевший refresh гасим best-effort вызовом
    // logout, чтобы не оставлять на сервере лишнюю живую сессию.
    if (!_isCurrent(generation)) {
      if (newRefreshToken != null) unawaited(_bestEffortLogout(newRefreshToken));
      throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
    }

    // Риск 3 плана `10-refresh.md`: новый refresh пишется раньше access,
    // чтобы сбой между записями оставлял в хранилище годный (уже
    // провёрнутый) refresh, а не пару из старого access и нового refresh,
    // рассинхронизированную с сервером.
    if (newRefreshToken != null) {
      await _storage.writeRefreshToken(newRefreshToken);
      if (!_isCurrent(generation)) {
        unawaited(_bestEffortLogout(newRefreshToken));
        throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
      }
    }

    await _storage.writeToken(response.accessToken);
    if (!_isCurrent(generation)) {
      if (newRefreshToken != null) unawaited(_bestEffortLogout(newRefreshToken));
      throw const ApiError(401, 'REFRESH_TOKEN_INVALID');
    }

    _setToken(response.accessToken);
    state = state.copyWith(token: response.accessToken);
    return response.accessToken;
  }

  /// Погасить осиротевший после смены поколения refresh — без гарантии
  /// успеха: если сеть недоступна, лишняя сессия на сервере не критична,
  /// а важнее не мешать уже текущей сессии пользователя.
  ///
  /// `skipAuthHeader: true` (Р3, ревью `10-refresh.md`): гасимый
  /// refresh-токен — чужой для текущей сессии, а перехватчик клиента иначе
  /// подставит `Authorization` текущей — сервер отзовёт её access вместо
  /// осиротевшего токена и вызовет лишний refresh.
  Future<void> _bestEffortLogout(String refreshToken) async {
    try {
      await auth_api.logout(_client, refreshToken: refreshToken, skipAuthHeader: true);
    } catch (_) {
      // best-effort — ошибки намеренно проглатываются.
    }
  }

  /// Обновить пользователя из ответа сервера, например после смены пароля.
  void updateUser(auth_api.User user) {
    state = state.copyWith(user: user);
  }

  /// Перечитать список членств — после создания учреждения или по
  /// «Повторить».
  Future<void> reloadMemberships() async {
    state = state.copyWith(memberships: null, membershipsError: null);
    if (!ref.mounted) return;
    await _loadMemberships();
  }

  /// Сменить текущее учреждение: при необходимости переключает контекст
  /// токена (`POST /institutions/{id}/token`) и запоминает выбор для
  /// автовыбора при следующем входе. Если контекст токена уже совпадает —
  /// повторного запроса нет.
  Future<void> selectInstitution(String institutionId) async {
    final token = state.token;
    if (token == null) return;
    // С2: поколение фиксируется на входе — если за время запроса случится
    // logout или 401, ответ ниже никуда не запишется.
    final generation = _generation;

    if (decodeInstitutionId(token) != institutionId) {
      final response = await auth_api.selectInstitution(_client, institutionId);
      if (!_isCurrent(generation)) return;
      await _storage.writeToken(response.accessToken);
      if (!_isCurrent(generation)) return;
      _setToken(response.accessToken);
      state = state.copyWith(token: response.accessToken);
    }
    if (!_isCurrent(generation)) return;
    await _storage.writeLastInstitutionId(institutionId);
    if (!_isCurrent(generation)) return;
    state = state.copyWith(needsInstitutionSelection: false);
    _refreshInstitution();
  }

  void clearNotice() {
    if (state.notice != null) state = state.copyWith(notice: null);
  }

  Future<void> _applyToken(String token, {String? refreshToken}) async {
    final previousToken = state.token;
    // Новый вход начинает новую сессию — поколение растёт сразу, до первого
    // await, чтобы отрезать все операции предыдущей сессии (например,
    // запоздалый _loadMemberships пользователя A не попадёт в состояние B).
    _generation++;
    final generation = _generation;
    _setToken(token);
    try {
      final user = await auth_api.getMe(_client);
      if (!_isCurrent(generation)) return;
      // Тот же порядок, что и при refresh (риск 3 плана `10-refresh.md`):
      // refresh раньше access.
      if (refreshToken != null) {
        await _storage.writeRefreshToken(refreshToken);
        if (!_isCurrent(generation)) return;
      }
      await _storage.writeToken(token);
      if (!_isCurrent(generation)) return;
      state = SessionState(status: SessionStatus.authed, token: token, user: user);
      unawaited(_loadMemberships());
    } catch (error) {
      // Откатываем токен, только если эта попытка входа ещё актуальна —
      // иначе более поздние logout/401/вход уже задали свой токен, и
      // затирать его предыдущим значением нельзя.
      if (_isCurrent(generation)) {
        _setToken(previousToken);
      }
      rethrow;
    }
  }

  Future<void> _loadMemberships() async {
    // Поколение своей сессии, не текущее на момент завершения запроса: если
    // за время ожидания случится перелогин, ответ этого запроса — чужой для
    // новой сессии и никуда не пишется.
    final generation = _generation;
    try {
      final loaded = await auth_api.getMyInstitutions(_client);
      if (!_isCurrent(generation)) return;
      state = state.copyWith(memberships: loaded, membershipsError: null);
      _refreshInstitution();
      await _autoSelectInstitution(loaded, generation);
    } catch (error) {
      if (!_isCurrent(generation)) return;
      state = state.copyWith(membershipsError: error);
    }
  }

  /// Автовыбор после входа и на холодном старте (В3/а): последнее выбранное
  /// активное членство — приоритет; иначе, если активное членство ровно
  /// одно, выбор очевиден. При нескольких активных или их отсутствии выбор
  /// не делается — экран выбора учреждения служит и онбордингом, и выбором.
  Future<void> _autoSelectInstitution(List<auth_api.Membership> memberships, int generation) async {
    final token = state.token;
    if (token == null) return;

    final active = memberships.where((item) => item.status == auth_api.MembershipStatus.active).toList();
    final lastId = await _storage.readLastInstitutionId();
    if (!_isCurrent(generation)) return;

    String? target;
    if (lastId != null && active.any((item) => item.institutionId == lastId)) {
      target = lastId;
    } else if (active.length == 1) {
      target = active.first.institutionId;
    }
    if (target == null) return;

    if (decodeInstitutionId(token) == target) {
      // Контекст уже верный — только фиксируем выбор для следующего раза.
      if (!_isCurrent(generation)) return;
      await _storage.writeLastInstitutionId(target);
      return;
    }

    try {
      final response = await auth_api.selectInstitution(_client, target);
      if (!_isCurrent(generation)) return;
      await _storage.writeToken(response.accessToken);
      if (!_isCurrent(generation)) return;
      await _storage.writeLastInstitutionId(target);
      if (!_isCurrent(generation)) return;
      _setToken(response.accessToken);
      state = state.copyWith(token: response.accessToken);
      _refreshInstitution();
    } catch (_) {
      // Автовыбор — необязательная попытка: при сбое пользователь выбирает
      // учреждение вручную на экране выбора.
    }
  }

  void _refreshInstitution() {
    final token = state.token;
    final memberships = state.memberships;
    InstitutionContext? institution;
    if (token != null && memberships != null) {
      final institutionId = decodeInstitutionId(token);
      if (institutionId != null) {
        final membership = _findActiveMembership(memberships, institutionId);
        if (membership != null) {
          institution = InstitutionContext(
            id: membership.institutionId,
            role: membership.role,
            name: membership.name,
            currencyName: membership.currencyName,
          );
        }
      }
    }
    state = state.copyWith(institution: institution);
  }

  auth_api.Membership? _findActiveMembership(List<auth_api.Membership> memberships, String institutionId) {
    for (final membership in memberships) {
      if (membership.institutionId == institutionId && membership.status == auth_api.MembershipStatus.active) {
        return membership;
      }
    }
    return null;
  }
}
