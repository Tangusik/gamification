// Тесты `TeachersScreen` (admin) — загрузка/ошибка/пусто, создание с 422 по
// полю и по коду `EMAIL_ALREADY_REGISTERED`, переименование и смена статуса.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/auth_api.dart' show MembershipStatus;
import 'package:gamification_mobile/screens/admin/teachers_screen.dart';

import '../staff/staff_test_support.dart';

Map<String, dynamic> teacherJson({
  String userId = 't1',
  String? displayName = 'Иван Иванов',
  String status = 'active',
  String createdAt = '2026-01-10T10:00:00Z',
  List<String> groupIds = const [],
}) => {
  'user_id': userId,
  'display_name': displayName,
  'status': status,
  'created_at': createdAt,
  'group_ids': groupIds,
};

void main() {
  testWidgets('загрузка сменяется данными', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, [teacherJson()]),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Иван Иванов'), findsOneWidget);
  });

  testWidgets('ошибка списка показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(500, {'detail': 'boom'}),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Повторить'), findsOneWidget);
  });

  testWidgets('403 показывает «Нет доступа»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(403, {'detail': 'INSUFFICIENT_ROLE'}),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: teacherSession());

    expect(find.text('Нет доступа'), findsOneWidget);
  });

  testWidgets('пустой список показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Преподавателей пока нет.'), findsOneWidget);
  });

  testWidgets('создание с 422 показывает ошибку у поля почты', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/teachers': (o, b) async => jsonResponse(422, {
            'detail': [
              {
                'loc': ['body', 'email'],
                'msg': 'value is not a valid email address',
              },
            ],
          }),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Почта'), 'not-an-email');
    await tester.enterText(find.widgetWithText(TextField, 'Временный пароль'), 'password123');
    await tester.enterText(find.widgetWithText(TextField, 'Имя'), 'Пётр Петров');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Добавить преподавателя'));
    await pumpFrames(tester);

    expect(find.text('value is not a valid email address'), findsOneWidget);
  });

  testWidgets('EMAIL_ALREADY_REGISTERED показывается у поля почты', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/teachers': (o, b) async => jsonResponse(409, {'detail': 'EMAIL_ALREADY_REGISTERED'}),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Почта'), 'exists@example.com');
    await tester.enterText(find.widgetWithText(TextField, 'Временный пароль'), 'password123');
    await tester.enterText(find.widgetWithText(TextField, 'Имя'), 'Пётр Петров');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Добавить преподавателя'));
    await pumpFrames(tester);

    expect(find.text('Пользователь с такой почтой уже зарегистрирован.'), findsOneWidget);
  });

  testWidgets('переименование отправляет PATCH и показывает «Сохранено»', (tester) async {
    var renamed = false;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async =>
          jsonResponse(200, [teacherJson(displayName: renamed ? 'Новое имя' : 'Иван Иванов')]),
      'PATCH /institutions/inst-1/teachers/t1': (o, b) async {
        renamed = true;
        return jsonResponse(200, teacherJson(displayName: 'Новое имя'));
      },
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Имя').last, 'Новое имя');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Сохранить имя'));
    await pumpFrames(tester);

    expect(adapter.requestBodies, hasLength(1));
    expect(adapter.requestBodies.first['display_name'], 'Новое имя');
    expect(find.text('Сохранено'), findsOneWidget);
  });

  testWidgets('приостановка требует подтверждения и отправляет PATCH', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, [teacherJson()]),
      'PATCH /institutions/inst-1/teachers/t1': (o, b) async => jsonResponse(200, teacherJson(status: 'suspended')),
    });

    await pumpScreen(tester, const TeachersScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.byType(DropdownButton<MembershipStatus>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('доступ приостановлен').last);
    await tester.pumpAndSettle();

    expect(find.text('Приостановить преподавателя?'), findsOneWidget);
    expect(adapter.requestBodies, isEmpty);

    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Приостановить')));
    await tester.pumpAndSettle();
    await pumpFrames(tester);

    expect(adapter.requestBodies, hasLength(1));
    expect(adapter.requestBodies.first['status'], 'suspended');
  });
}
