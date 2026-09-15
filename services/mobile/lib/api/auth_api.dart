/// Вызовы публичных эндпоинтов сервиса `users` и членств (`GET /institutions`,
/// `POST /institutions/{id}/token`) — зеркало
/// `services/web/src/api/auth.ts`, та же граница: `getMyInstitutions` и
/// `selectInstitution` исторически лежат здесь, а не в `institutions_api.dart`.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'client.dart';

/// Признак мобильного клиента (план `10-refresh.md`, раздел 3): путь
/// предъявления refresh обязан совпадать с путём выдачи (У4) — у веба это
/// cookie, у мобильного — тело запроса. Заголовок нужен на всех трёх путях
/// `jwt/{login,refresh,logout}`.
const Map<String, String> _mobileClientHeader = {'X-Client': 'mobile'};

class TokenResponse {
  const TokenResponse({required this.accessToken, required this.tokenType, this.refreshToken});

  factory TokenResponse.fromJson(Map<String, dynamic> json) => TokenResponse(
        accessToken: json['access_token'] as String,
        tokenType: json['token_type'] as String,
        refreshToken: json['refresh_token'] as String?,
      );

  final String accessToken;
  final String tokenType;

  /// Приходит только мобильному клиенту (`X-Client: mobile`) — на вход и на
  /// каждый refresh, с ротацией.
  final String? refreshToken;
}

class User {
  const User({
    required this.id,
    required this.email,
    required this.isActive,
    required this.isSuperuser,
    required this.isVerified,
    required this.createdAt,
    required this.mustChangePassword,
  });

  factory User.fromJson(Map<String, dynamic> json) => User(
        id: json['id'] as String,
        email: json['email'] as String,
        isActive: json['is_active'] as bool,
        isSuperuser: json['is_superuser'] as bool,
        isVerified: json['is_verified'] as bool,
        createdAt: DateTime.parse(json['created_at'] as String),
        mustChangePassword: json['must_change_password'] as bool,
      );

  final String id;
  final String email;
  final bool isActive;
  final bool isSuperuser;
  final bool isVerified;
  final DateTime createdAt;

  /// Пока стоит — приложение уводит на смену пароля.
  final bool mustChangePassword;
}

enum InstitutionKind {
  school,
  camp;

  static InstitutionKind fromJson(String value) => switch (value) {
        'school' => InstitutionKind.school,
        'camp' => InstitutionKind.camp,
        _ => throw ArgumentError('Неизвестный InstitutionKind: $value'),
      };

  String toJson() => switch (this) {
        InstitutionKind.school => 'school',
        InstitutionKind.camp => 'camp',
      };
}

enum UserRole {
  student,
  teacher,
  institutionAdmin;

  static UserRole fromJson(String value) => switch (value) {
        'student' => UserRole.student,
        'teacher' => UserRole.teacher,
        'institution_admin' => UserRole.institutionAdmin,
        _ => throw ArgumentError('Неизвестный UserRole: $value'),
      };

  String toJson() => switch (this) {
        UserRole.student => 'student',
        UserRole.teacher => 'teacher',
        UserRole.institutionAdmin => 'institution_admin',
      };
}

enum MembershipStatus {
  invited,
  active,
  suspended;

  static MembershipStatus fromJson(String value) => switch (value) {
        'invited' => MembershipStatus.invited,
        'active' => MembershipStatus.active,
        'suspended' => MembershipStatus.suspended,
        _ => throw ArgumentError('Неизвестный MembershipStatus: $value'),
      };

  String toJson() => switch (this) {
        MembershipStatus.invited => 'invited',
        MembershipStatus.active => 'active',
        MembershipStatus.suspended => 'suspended',
      };
}

class Membership {
  const Membership({
    required this.institutionId,
    required this.name,
    required this.kind,
    required this.role,
    required this.status,
    required this.currencyName,
  });

  factory Membership.fromJson(Map<String, dynamic> json) => Membership(
        institutionId: json['institution_id'] as String,
        name: json['name'] as String,
        kind: InstitutionKind.fromJson(json['kind'] as String),
        role: UserRole.fromJson(json['role'] as String),
        status: MembershipStatus.fromJson(json['status'] as String),
        currencyName: json['currency_name'] as String?,
      );

  final String institutionId;
  final String name;
  final InstitutionKind kind;
  final UserRole role;
  final MembershipStatus status;

  /// Название внутренней валюты учреждения; `null`, пока не задано.
  final String? currencyName;
}

Future<User> register(ApiClient client, {required String email, required String password}) {
  return client
      .request<Map<String, dynamic>>(
    '/users/auth/register',
    method: 'POST',
    json: {'email': email, 'password': password},
  )
      .then(User.fromJson);
}

/// Вход. Тело — form-urlencoded с полями `username` и `password`: стандартная
/// форма OAuth2 из `fastapi-users`, JSON здесь не принимается.
///
/// `X-Client: mobile` — иначе сервер решит, что это веб, и refresh-токен
/// уйдёт только в `Set-Cookie`, которую мобильный клиент не читает.
Future<TokenResponse> login(ApiClient client, {required String email, required String password}) {
  return client
      .request<Map<String, dynamic>>(
    '/users/auth/jwt/login',
    method: 'POST',
    form: {'username': email, 'password': password},
    headers: _mobileClientHeader,
  )
      .then(TokenResponse.fromJson);
}

/// Обновить пару токенов по refresh-токену (план `10-refresh.md`).
///
/// `institutionId` — последнее выбранное учреждение; сервер подтверждает
/// членство сам и либо возвращает контекст, либо нет (`INSTITUTION_CONTEXT`
/// в claim), само поле не обязательно. Путь исключён из авто-обновления в
/// `ApiClient`, поэтому 401 отсюда не запускает вложенный refresh.
Future<TokenResponse> refresh(ApiClient client, {required String refreshToken, String? institutionId}) {
  final body = <String, dynamic>{'refresh_token': refreshToken};
  if (institutionId != null) body['institution_id'] = institutionId;
  return client
      .request<Map<String, dynamic>>(
    '/users/auth/jwt/refresh',
    method: 'POST',
    json: body,
    headers: _mobileClientHeader,
  )
      .then(TokenResponse.fromJson);
}

/// Выход на сервере: гасит сессию по refresh-токену и, если предъявлен
/// действующий access, его `jti` — в denylist. Ответ — 204 без тела, сервер
/// отвечает так же и на уже погашенный токен (У10 плана `10-refresh.md`).
///
/// Сама безусловность выхода (чистить сессию даже без сети) — решение Ч3.
///
/// `skipAuthHeader` (Р3, ревью `10-refresh.md`) — не слать `Authorization`
/// текущей сессии: для best-effort гашения осиротевшего refresh-токена
/// (`SessionNotifier._bestEffortLogout`) чужой Bearer лишний — сервер отзовёт
/// доступ по нему, а не по гасимому refresh-токену.
Future<void> logout(ApiClient client, {String? refreshToken, bool skipAuthHeader = false}) {
  return client.request<void>(
    '/users/auth/jwt/logout',
    method: 'POST',
    json: refreshToken != null ? {'refresh_token': refreshToken} : null,
    headers: _mobileClientHeader,
    extra: skipAuthHeader ? {ApiClient.skipAuthExtraKey: true} : null,
  );
}

Future<User> getMe(ApiClient client) {
  return client.request<Map<String, dynamic>>('/users/me').then(User.fromJson);
}

/// Сменить свой пароль. Ответ — обновлённый пользователь с
/// `mustChangePassword: false`; текущий пароль сервер не спрашивает.
Future<User> changePassword(ApiClient client, String password) {
  return client
      .request<Map<String, dynamic>>('/users/me', method: 'PATCH', json: {'password': password})
      .then(User.fromJson);
}

Future<List<Membership>> getMyInstitutions(ApiClient client) {
  return client.request<List<dynamic>>('/institutions').then(
        (list) => list.map((item) => Membership.fromJson(item as Map<String, dynamic>)).toList(),
      );
}

/// Выбрать учреждение. Ответ содержит новый токен, который заменяет текущий:
/// срок жизни у него — остаток жизни предъявленного.
Future<TokenResponse> selectInstitution(ApiClient client, String institutionId) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions/${Uri.encodeComponent(institutionId)}/token',
    method: 'POST',
  )
      .then(TokenResponse.fromJson);
}
