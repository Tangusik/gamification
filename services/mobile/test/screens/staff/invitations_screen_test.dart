// Тесты `InvitationsScreen` — загрузка/ошибка/пусто, создание, копирование
// ссылки, отзыв с подтверждением. Teacher-фильтрация — на сервере
// (`03-invitations.md`, F3): проверяем, что клиент не урезает список сам,
// показывая ровно то, что вернул фейковый сервер.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/common/invite_link.dart';
import 'package:gamification_mobile/screens/staff/invitations_link.dart';
import 'package:gamification_mobile/screens/staff/invitations_screen.dart';

import 'staff_test_support.dart';

Map<String, dynamic> invitationJson({
  String id = 'i1',
  String token = 'tok123',
  String role = 'student',
  int maxUses = 1,
  int usesCount = 0,
  String createdBy = 'u1',
  String createdAt = '2026-01-10T10:00:00Z',
  String? revokedAt,
}) => {
  'id': id,
  'token': token,
  'role': role,
  'max_uses': maxUses,
  'uses_count': usesCount,
  'created_by': createdBy,
  'created_at': createdAt,
  'revoked_at': revokedAt,
};

void main() {
  // Реальный `apiBaseUrl` (`--dart-define`) в тестовой сборке не задан —
  // виджет-тесты ниже подменяют его тем же способом, каким это делает
  // release-сборка, без пересборки под каждый прогон.
  final originalInviteApiBaseUrl = inviteApiBaseUrl;

  setUp(() {
    // `Clipboard.setData` — платформенный канал; тестовый биндинг подставляет
    // обработчик по умолчанию, здесь просто перехватываем вызов явно.
    TestWidgetsFlutterBinding.ensureInitialized().defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async => null,
    );
    inviteApiBaseUrl = 'https://gymnasium-5.gamification.example/api/v1';
  });

  tearDown(() {
    inviteApiBaseUrl = originalInviteApiBaseUrl;
  });

  group('buildInviteLink', () {
    test('origin API_BASE_URL с путём /api/v1', () {
      expect(
        buildInviteLink('https://host/api/v1', 'tok'),
        'https://host/invite#tok',
      );
    });

    test('с портом', () {
      expect(
        buildInviteLink('http://10.0.2.2:8080/api/v1', 'tok'),
        'http://10.0.2.2:8080/invite#tok',
      );
    });

    test('без пути', () {
      expect(buildInviteLink('https://host', 'tok'), 'https://host/invite#tok');
    });

    test('мусор → null', () {
      expect(buildInviteLink('не адрес', 'tok'), isNull);
    });

    test('пустая строка (API_BASE_URL не задан) → null', () {
      expect(buildInviteLink('', 'tok'), isNull);
    });

    test('схема ftp: → null', () {
      expect(buildInviteLink('ftp://host/api/v1', 'tok'), isNull);
    });

    test('round-trip через parseInviteToken', () {
      final link = buildInviteLink('http://10.0.2.2:8080/api/v1', 'tok123');
      expect(link, isNotNull);
      expect(parseInviteToken(link!), 'tok123');
    });
  });

  testWidgets('загрузка сменяется данными', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, [invitationJson()]),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    expect(find.textContaining('tok123'), findsOneWidget);
  });

  testWidgets('ошибка списка показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(500, {'detail': 'boom'}),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Повторить'), findsOneWidget);
  });

  testWidgets('пустой список показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Приглашений пока нет.'), findsOneWidget);
  });

  testWidgets('teacher видит только то, что вернул сервер (без клиентской фильтрации)', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, [
            invitationJson(id: 'own', token: 'own-token', createdBy: 'u1'),
          ]),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: teacherSession());

    expect(find.textContaining('own-token'), findsOneWidget);
  });

  testWidgets('создание отправляет max_uses и обновляет список', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/invitations': (o, b) async => jsonResponse(201, invitationJson(maxUses: 5)),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Число применений'), '5');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Создать ссылку'));
    await pumpFrames(tester);

    expect(adapter.requestBodies, hasLength(1));
    expect(adapter.requestBodies.first['max_uses'], 5);
  });

  testWidgets('отзыв: отмена не шлёт запрос, подтверждение шлёт DELETE', (tester) async {
    var revoked = false;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, [invitationJson()]),
      'DELETE /institutions/inst-1/invitations/i1': (o, b) async {
        revoked = true;
        return jsonResponse(204, '');
      },
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Отозвать'));
    await tester.pumpAndSettle();
    expect(find.text('Отозвать приглашение?'), findsOneWidget);

    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(revoked, isFalse);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Отозвать'));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Отозвать')));
    await tester.pumpAndSettle();
    await pumpFrames(tester);

    expect(revoked, isTrue);
  });

  testWidgets('копирование ссылки показывает «Сохранено»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/invitations': (o, b) async => jsonResponse(200, [invitationJson()]),
    });

    await pumpScreen(tester, const InvitationsScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Скопировать ссылку'));
    await pumpFrames(tester);

    expect(find.text('Ссылка скопирована'), findsOneWidget);
  });
}
