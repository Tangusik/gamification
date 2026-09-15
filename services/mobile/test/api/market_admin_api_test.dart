// Каталог и очередь решений маркета (09c) — путь, метод, тело запроса и
// фильтр `listPurchases`.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/api/market_admin_api.dart';

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

Map<String, dynamic> _privilegeJson() => {
  'id': 'p1',
  'title': 'Пропуск домашки',
  'description': null,
  'price': 100,
  'stock': null,
  'is_active': true,
};

Map<String, dynamic> _purchaseJson({String status = 'pending'}) => {
  'id': 'pu1',
  'privilege_id': 'p1',
  'title': 'Пропуск домашки',
  'price': 100,
  'status': status,
  'created_at': '2026-09-01T10:00:00Z',
  'resolved_at': null,
  'user_id': 'u1',
  'user_name': 'Вася',
};

void main() {
  test('createPrivilege отправляет POST с телом без непереданных полей', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(201, _privilegeJson()));
    final client = _buildClient(adapter);

    await createPrivilege(client, 'inst-1', const CreatePrivilegeInput(title: 'Пропуск домашки', price: 100));

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/privileges');
    expect(adapter.requestBodies.single, {'title': 'Пропуск домашки', 'price': 100});
  });

  test('updatePrivilege отправляет PATCH и явно очищает stock через unsetField', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _privilegeJson()));
    final client = _buildClient(adapter);

    await updatePrivilege(
      client,
      'inst-1',
      'p1',
      const UpdatePrivilegeInput(price: 150, stock: null),
    );

    expect(adapter.lastRequest?.method, 'PATCH');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/privileges/p1');
    expect(adapter.requestBodies.single, {'price': 150, 'stock': null});
  });

  test('updatePrivilege по умолчанию не передаёт stock и description', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _privilegeJson()));
    final client = _buildClient(adapter);

    await updatePrivilege(client, 'inst-1', 'p1', const UpdatePrivilegeInput(title: 'Новое'));

    expect(adapter.requestBodies.single, {'title': 'Новое'});
  });

  test('listPurchases с фильтром status кодирует query-параметр', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, [_purchaseJson()]));
    final client = _buildClient(adapter);

    final purchases = await listPurchases(
      client,
      'inst-1',
      filter: const ListPurchasesFilter(status: PurchaseStatus.pending),
    );

    expect(adapter.lastRequest?.method, 'GET');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/purchases?status=pending');
    expect(purchases.single.userId, 'u1');
    expect(purchases.single.userName, 'Вася');
  });

  test('listPurchases с фильтром status и user_id кодирует оба параметра', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, [_purchaseJson()]));
    final client = _buildClient(adapter);

    await listPurchases(
      client,
      'inst-1',
      filter: const ListPurchasesFilter(status: PurchaseStatus.fulfilled, userId: 'u1'),
    );

    expect(adapter.lastRequest?.path, '/institutions/inst-1/purchases?status=fulfilled&user_id=u1');
  });

  test('listPurchases без фильтра не добавляет query', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, <Object>[]));
    final client = _buildClient(adapter);

    await listPurchases(client, 'inst-1');

    expect(adapter.lastRequest?.path, '/institutions/inst-1/purchases');
  });

  test('fulfilPurchase отправляет POST на .../fulfil', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _purchaseJson(status: 'fulfilled')));
    final client = _buildClient(adapter);

    final result = await fulfilPurchase(client, 'inst-1', 'pu1');

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/purchases/pu1/fulfil');
    expect(result.status, PurchaseStatus.fulfilled);
  });

  test('rejectPurchase отправляет POST на .../reject', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, _purchaseJson(status: 'rejected')));
    final client = _buildClient(adapter);

    final result = await rejectPurchase(client, 'inst-1', 'pu1');

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/purchases/pu1/reject');
    expect(result.status, PurchaseStatus.rejected);
  });
}
