// Начисление, сторно и история одного ученика (09b) — путь, метод и тело
// запроса, разбор моделей. Тот же приём фейкового адаптера, что в
// `test/screens/student/test_support.dart`.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/api/staff_currency_api.dart';

class _RecordingAdapter implements HttpClientAdapter {
  _RecordingAdapter(this._handler);

  final Future<ResponseBody> Function(RequestOptions options, Map<String, dynamic>? body) _handler;
  final List<Map<String, dynamic>> requestBodies = [];
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    Map<String, dynamic>? body;
    if (requestStream != null) {
      final bytes = await requestStream.fold<List<int>>([], (acc, chunk) => acc..addAll(chunk));
      if (bytes.isNotEmpty) {
        final decoded = jsonDecode(utf8.decode(bytes));
        if (decoded is Map<String, dynamic>) {
          body = decoded;
          requestBodies.add(decoded);
        }
      }
    }
    lastRequest = options;
    return _handler(options, body);
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

Map<String, dynamic> _transactionJson({
  String id = 't1',
  String kind = 'manual_accrual',
  int amount = 10,
  String? reversesId,
}) => {
  'id': id,
  'kind': kind,
  'amount': amount,
  'comment': null,
  'created_by_name': 'Иван Иванов',
  'created_by_role': 'teacher',
  'created_at': '2026-09-01T10:00:00Z',
  'reverses_id': reversesId,
};

void main() {
  test('accrue отправляет POST по нужному пути с телом операции', () async {
    final adapter = _RecordingAdapter((options, body) async => _jsonResponse(201, _transactionJson()));
    final client = _buildClient(adapter);

    final result = await accrue(
      client,
      'inst-1',
      'u1',
      const AccrueInput(operationId: 'op-1', amount: 15, comment: 'за домашку'),
    );

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/students/u1/currency-transactions');
    expect(adapter.requestBodies.single, {
      'operation_id': 'op-1',
      'amount': 15,
      'comment': 'за домашку',
    });
    expect(result.amount, 10);
  });

  test('accrue без комментария не отправляет поле comment', () async {
    final adapter = _RecordingAdapter((options, body) async => _jsonResponse(201, _transactionJson()));
    final client = _buildClient(adapter);

    await accrue(client, 'inst-1', 'u1', const AccrueInput(operationId: 'op-1', amount: 15));

    expect(adapter.requestBodies.single, {'operation_id': 'op-1', 'amount': 15});
  });

  test('reverse отправляет POST на .../reversal с operation_id', () async {
    final adapter = _RecordingAdapter(
      (options, body) async => _jsonResponse(201, _transactionJson(id: 't2', kind: 'reversal', amount: -10, reversesId: 't1')),
    );
    final client = _buildClient(adapter);

    final result = await reverse(client, 'inst-1', 't1', 'op-2');

    expect(adapter.lastRequest?.method, 'POST');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/currency-transactions/t1/reversal');
    expect(adapter.requestBodies.single, {'operation_id': 'op-2'});
    expect(result.reversesId, 't1');
    expect(result.amount, -10);
  });

  test('listStudentTransactions читает баланс и историю ученика', () async {
    final adapter = _RecordingAdapter(
      (options, body) async => _jsonResponse(200, {
        'balance': 42,
        'transactions': [_transactionJson()],
      }),
    );
    final client = _buildClient(adapter);

    final account = await listStudentTransactions(client, 'inst-1', 'u1');

    expect(adapter.lastRequest?.method, 'GET');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/students/u1/currency-transactions');
    expect(account.balance, 42);
    expect(account.transactions, hasLength(1));
  });
}
