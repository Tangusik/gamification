// Настройки учреждения и приглашения (09b/09c) — путь, метод, тело запроса.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/api/institution_admin_api.dart';

class _RecordingAdapter implements HttpClientAdapter {
  _RecordingAdapter(this._handler);

  final Future<ResponseBody> Function(RequestOptions options) _handler;
  final List<Map<String, dynamic>> requestBodies = [];
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (requestStream != null) {
      final bytes = await requestStream.fold<List<int>>([], (acc, chunk) => acc..addAll(chunk));
      if (bytes.isNotEmpty) {
        final decoded = jsonDecode(utf8.decode(bytes));
        if (decoded is Map<String, dynamic>) requestBodies.add(decoded);
      }
    }
    lastRequest = options;
    return _handler(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _jsonResponse(int statusCode, Object body) {
  return ResponseBody.fromString(
    jsonEncode(body),
    statusCode,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

ApiClient _buildClient(_RecordingAdapter adapter) {
  final dio = Dio(BaseOptions(validateStatus: (status) => status != null && status >= 200 && status < 300));
  dio.httpClientAdapter = adapter;
  return ApiClient(tokenProvider: () => 't', dio: dio);
}

Map<String, dynamic> _institutionJson({String? currencyName = 'коины'}) => {
  'id': 'inst-1',
  'name': 'Школа №1',
  'kind': 'school',
  'created_at': '2026-01-01T00:00:00Z',
  'currency_name': currencyName,
};

void main() {
  test('getInstitution читает учреждение по id', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _institutionJson()));
    final client = _buildClient(adapter);

    final institution = await getInstitution(client, 'inst-1');

    expect(adapter.lastRequest?.method, 'GET');
    expect(adapter.lastRequest?.path, '/institutions/inst-1');
    expect(institution.currencyName, 'коины');
  });

  test('updateInstitution отправляет только переданные поля', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _institutionJson()));
    final client = _buildClient(adapter);

    await updateInstitution(client, 'inst-1', const UpdateInstitutionInput(name: 'Новое имя'));

    expect(adapter.lastRequest?.method, 'PATCH');
    expect(adapter.lastRequest?.path, '/institutions/inst-1');
    expect(adapter.requestBodies.single, {'name': 'Новое имя'});
  });

  test('updateInstitution с currencyName: null явно очищает название валюты', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _institutionJson(currencyName: null)));
    final client = _buildClient(adapter);

    await updateInstitution(client, 'inst-1', const UpdateInstitutionInput(currencyName: null));

    expect(adapter.requestBodies.single, {'currency_name': null});
  });

  test('createInvitation отправляет POST с max_uses', () async {
    final adapter = _RecordingAdapter(
      (options) async => _jsonResponse(201, {
        'id': 'inv1',
        'token': 'tok',
        'role': 'student',
        'max_uses': 5,
        'uses_count': 0,
        'created_by': 'u1',
        'created_at': '2026-01-01T00:00:00Z',
        'revoked_at': null,
      }),
    );
    final client = _buildClient(adapter);

    final invitation = await createInvitation(client, 'inst-1', 5);

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/invitations');
    expect(adapter.requestBodies.single, {'max_uses': 5});
    expect(invitation.maxUses, 5);
  });

  test('revokeInvitation отправляет DELETE по адресу приглашения', () async {
    final adapter = _RecordingAdapter((options) async => ResponseBody.fromString('', 204));
    final client = _buildClient(adapter);

    await revokeInvitation(client, 'inst-1', 'inv1');

    expect(adapter.lastRequest?.method, 'DELETE');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/invitations/inv1');
  });
}
