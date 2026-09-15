import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/auth/token_storage.dart';
import 'package:gamification_mobile/screens/admin/institution_settings_screen.dart';

import '../staff/staff_test_support.dart';

/// `reloadMemberships()` (вызывается после сохранения настроек) перечитывает
/// `GET /institutions` и пересобирает `sessionProvider.institution` из
/// `institution_id`, зашитого в access-токене (`lib/auth/claims.dart`).
/// `staff_test_support.dart` использует токен-заглушку `'t'`, который не
/// разбирается как JWT — для этого сценария нужен настоящий (по форме)
/// токен, поэтому здесь собственный токен и обёртка над `pumpScreen`.
String _fakeJwt(String institutionId) {
  String segment(Object payload) =>
      base64Url.encode(utf8.encode(jsonEncode(payload))).replaceAll('=', '');
  final header = segment({'alg': 'none'});
  final payload = segment({
    'institution_id': institutionId,
    'exp': DateTime.now().toUtc().add(const Duration(hours: 1)).millisecondsSinceEpoch ~/ 1000,
  });
  return '$header.$payload.sig';
}

Future<ProviderContainer> _pumpSettings(
  WidgetTester tester, {
  required RecordingAdapter adapter,
  String institutionId = 'inst-1',
  String? currencyName = 'коины',
}) async {
  final session = SessionState(
    status: SessionStatus.authed,
    token: _fakeJwt(institutionId),
    institution: InstitutionContext(
      id: institutionId,
      role: adminSession().institution!.role,
      name: 'Школа №1',
      currencyName: currencyName,
    ),
  );
  final container = ProviderContainer(
    overrides: [
      sessionProvider.overrideWith(() => FixedSessionNotifier(session)),
      apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
      tokenStorageProvider.overrideWithValue(InMemoryTokenStorage()),
    ],
  );
  addTearDown(container.dispose);
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp(home: const InstitutionSettingsScreen()),
    ),
  );
  await pumpFrames(tester);
  return container;
}

Map<String, dynamic> _institutionJson({
  String id = 'inst-1',
  String name = 'Школа №1',
  String kind = 'school',
  String? currencyName = 'коины',
}) => {
  'id': id,
  'name': name,
  'kind': kind,
  'created_at': '2026-01-01T00:00:00Z',
  'currency_name': currencyName,
};

Map<String, dynamic> _membershipJson({
  String institutionId = 'inst-1',
  String name = 'Школа №1',
  String kind = 'school',
  String role = 'institution_admin',
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

void main() {
  testWidgets('загрузка → данные', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1': (o, b) async => jsonResponse(200, _institutionJson()),
    });

    await _pumpSettings(tester, adapter: adapter);

    expect(find.widgetWithText(TextField, 'Название').first, findsOneWidget);
  });

  testWidgets('ошибка загрузки показывает «Повторить»', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1': (o, b) async {
        attempt += 1;
        if (attempt == 1) return jsonResponse(500, {'detail': 'BOOM'});
        return jsonResponse(200, _institutionJson());
      },
    });

    await _pumpSettings(tester, adapter: adapter);
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await pumpFrames(tester);

    expect(find.widgetWithText(TextField, 'Название'), findsOneWidget);
  });

  testWidgets('422 показывает ошибку у поля', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1': (o, b) async => jsonResponse(200, _institutionJson()),
      'PATCH /institutions/inst-1': (o, b) async => jsonResponse(422, {
        'detail': [
          {
            'loc': ['body', 'name'],
            'msg': 'Название обязательно',
          },
        ],
      }),
    });

    await _pumpSettings(tester, adapter: adapter);

    await tester.enterText(find.widgetWithText(TextField, 'Название'), '');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Сохранить'));
    await pumpFrames(tester);

    expect(find.text('Название обязательно'), findsOneWidget);
  });

  testWidgets('сохранение currency_name обновляет currencyName в сессии', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1': (o, b) async => jsonResponse(200, _institutionJson()),
      'PATCH /institutions/inst-1': (o, b) async =>
          jsonResponse(200, _institutionJson(currencyName: 'жетоны')),
      'GET /institutions': (o, b) async => jsonResponse(200, [_membershipJson(currencyName: 'жетоны')]),
    });

    final container = await _pumpSettings(tester, adapter: adapter);

    await tester.enterText(find.widgetWithText(TextField, 'Название валюты (пусто — по умолчанию)'), 'жетоны');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Сохранить'));
    await pumpFrames(tester);

    expect(find.text('Сохранено'), findsOneWidget);
    expect(container.read(sessionProvider).institution?.currencyName, 'жетоны');
  });
}
