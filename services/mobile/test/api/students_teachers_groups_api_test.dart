// Разбор моделей и путь/метод запросов для учеников, преподавателей и групп
// (09b). Полное покрытие CRUD не требуется — таблица методов уже проверена
// на примере валюты и маркета (см. `staff_currency_api_test.dart`,
// `market_admin_api_test.dart`); здесь достаточно по одному характерному
// случаю на файл плюс разбор моделей.
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/client.dart';
import 'package:gamification_mobile/api/groups_api.dart';
import 'package:gamification_mobile/api/students_api.dart';
import 'package:gamification_mobile/api/teachers_api.dart';

class _RecordingAdapter implements HttpClientAdapter {
  _RecordingAdapter(this._handler);

  final Future<ResponseBody> Function(RequestOptions options) _handler;
  RequestOptions? lastRequest;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
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

void main() {
  test('listStudents с group_id добавляет query-параметр', () async {
    final adapter = _RecordingAdapter(
      (options) async => _jsonResponse(200, [
        {
          'user_id': 'u1',
          'display_name': 'Вася',
          'status': 'active',
          'created_at': '2026-01-01T00:00:00Z',
          'group_ids': ['g1'],
          'balance': 50,
        },
      ]),
    );
    final client = _buildClient(adapter);

    final students = await listStudents(client, 'inst-1', groupId: 'g1');

    expect(adapter.lastRequest?.method, 'GET');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/students?group_id=g1');
    expect(students.single.balance, 50);
    expect(students.single.groupIds, ['g1']);
  });

  test('listStudents без group_id не добавляет query', () async {
    final adapter = _RecordingAdapter((options) async => _jsonResponse(200, <Object>[]));
    final client = _buildClient(adapter);

    await listStudents(client, 'inst-1');

    expect(adapter.lastRequest?.path, '/institutions/inst-1/students');
  });

  test('listTeachers разбирает InstitutionMember', () async {
    final adapter = _RecordingAdapter(
      (options) async => _jsonResponse(200, [
        {
          'user_id': 'u2',
          'display_name': null,
          'status': 'invited',
          'created_at': '2026-01-01T00:00:00Z',
          'group_ids': <String>[],
        },
      ]),
    );
    final client = _buildClient(adapter);

    final teachers = await listTeachers(client, 'inst-1');

    expect(adapter.lastRequest?.path, '/institutions/inst-1/teachers');
    expect(teachers.single.displayName, isNull);
  });

  test('listGroups разбирает Group', () async {
    final adapter = _RecordingAdapter(
      (options) async => _jsonResponse(200, [
        {
          'id': 'g1',
          'name': 'Группа А',
          'teacher_ids': ['u3'],
          'students_count': 12,
        },
      ]),
    );
    final client = _buildClient(adapter);

    final groups = await listGroups(client, 'inst-1');

    expect(adapter.lastRequest?.path, '/institutions/inst-1/groups');
    expect(groups.single.studentsCount, 12);
  });

  test('addStudentToGroup отправляет PUT по адресу студента в группе', () async {
    final adapter = _RecordingAdapter((options) async => ResponseBody.fromString('', 204));
    final client = _buildClient(adapter);

    await addStudentToGroup(client, 'inst-1', 'g1', 'u1');

    expect(adapter.lastRequest?.method, 'PUT');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/groups/g1/students/u1');
  });

  test('removeTeacherFromGroup отправляет DELETE по адресу преподавателя в группе', () async {
    final adapter = _RecordingAdapter((options) async => ResponseBody.fromString('', 204));
    final client = _buildClient(adapter);

    await removeTeacherFromGroup(client, 'inst-1', 'g1', 'u3');

    expect(adapter.lastRequest?.method, 'DELETE');
    expect(adapter.lastRequest?.path, '/institutions/inst-1/groups/g1/teachers/u3');
  });
}
