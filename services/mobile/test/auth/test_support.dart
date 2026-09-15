// Общие фикстуры для тестов Ч3 — тот же приём подмены сети, что в
// `test/api/client_test.dart`: свой `HttpClientAdapter` без дополнительных
// зависимостей.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:gamification_mobile/api/client.dart';

class FakeAdapter implements HttpClientAdapter {
  FakeAdapter(this._handler);

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

/// Клиент API поверх фейковой сети — токен в заголовке фейковому бэкенду не
/// нужен, поэтому `tokenProvider` здесь не участвует в тестах сессии.
ApiClient buildFakeApiClient(Future<ResponseBody> Function(RequestOptions options) handler) {
  return ApiClient(tokenProvider: () => null, dio: buildFakeDio(handler));
}

/// Тот же фейковый `Dio`, что и в [buildFakeApiClient], без готового
/// `ApiClient` — для тестов, которым нужна настоящая привязка токена и
/// поколения сессии к `ApiClient` (`apiClientDioProvider`, Р2 ревью
/// `10-refresh.md`), а не фиксированный `tokenProvider: () => null`.
Dio buildFakeDio(Future<ResponseBody> Function(RequestOptions options) handler) {
  final dio = Dio(BaseOptions(validateStatus: (status) => status != null && status >= 200 && status < 300));
  dio.httpClientAdapter = FakeAdapter(handler);
  return dio;
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

Map<String, dynamic> userJson({String id = 'u1', bool mustChangePassword = false}) => {
  'id': id,
  'email': 'user@example.com',
  'is_active': true,
  'is_superuser': false,
  'is_verified': true,
  'created_at': '2026-01-01T00:00:00Z',
  'must_change_password': mustChangePassword,
};

Map<String, dynamic> membershipJson({
  required String institutionId,
  String name = 'Школа №1',
  String kind = 'school',
  String role = 'student',
  String status = 'active',
  String? currencyName = 'коины',
}) => {
  'institution_id': institutionId,
  'name': name,
  'kind': kind,
  'role': role,
  'status': status,
  'currency_name': currencyName,
};

Map<String, dynamic> tokenJson(String token) => {'access_token': token, 'token_type': 'bearer'};

/// Собрать JWT-подобную строку с нужными claims — подпись фиктивная, разбор
/// в `lib/auth/claims.dart` её не проверяет.
String fakeJwt(Map<String, dynamic> payload) {
  String segment(Object value) {
    final text = value is String ? value : jsonEncode(value);
    return base64Url.encode(utf8.encode(text)).replaceAll('=', '');
  }

  return '${segment({
    'alg': 'RS256',
  })}.${segment(payload)}.signature';
}

int unixSecondsFromNow(Duration offset) =>
    DateTime.now().toUtc().add(offset).millisecondsSinceEpoch ~/ 1000;
