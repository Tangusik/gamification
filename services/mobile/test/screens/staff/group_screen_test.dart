// Тесты `GroupScreen` — загрузка/ошибка/«не найдена», состав преподавателей
// и учеников, разграничение ролей (admin меняет состав и удаляет группу,
// teacher — только читает) и подтверждение удаления.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/group_screen.dart';

import 'staff_test_support.dart';

Map<String, dynamic> groupJson({
  String id = 'g1',
  String name = '9 «А»',
  List<String> teacherIds = const [],
  int studentsCount = 0,
}) => {
  'id': id,
  'name': name,
  'teacher_ids': teacherIds,
  'students_count': studentsCount,
};

Map<String, dynamic> memberJson({
  required String userId,
  String? displayName,
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

Map<String, dynamic> studentJson({
  required String userId,
  String? displayName,
  String status = 'active',
  String createdAt = '2026-01-10T10:00:00Z',
  List<String> groupIds = const [],
  int balance = 0,
}) => {
  ...memberJson(userId: userId, displayName: displayName, status: status, createdAt: createdAt, groupIds: groupIds),
  'balance': balance,
};

void main() {
  testWidgets('загрузка сменяется данными', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson()]),
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/students?group_id=g1': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'g1'), adapter: adapter, session: adminSession());

    expect(find.text('9 «А»'), findsWidgets);
  });

  testWidgets('ошибка списка групп показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(500, {'detail': 'boom'}),
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'g1'), adapter: adapter, session: adminSession());

    expect(find.text('Повторить'), findsOneWidget);
  });

  testWidgets('несуществующая группа показывает «Группа не найдена.»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'missing'), adapter: adapter, session: adminSession());

    expect(find.text('Группа не найдена.'), findsOneWidget);
  });

  testWidgets('admin видит состав и может добавить преподавателя', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson()]),
      'GET /institutions/inst-1/teachers': (o, b) async =>
          jsonResponse(200, [memberJson(userId: 'te1', displayName: 'Мария Петрова')]),
      'GET /institutions/inst-1/students?group_id=g1': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, <Object>[]),
      'PUT /institutions/inst-1/groups/g1/teachers/te1': (o, b) async => jsonResponse(204, ''),
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'g1'), adapter: adapter, session: adminSession());

    expect(find.text('В группе нет преподавателей.'), findsOneWidget);
    expect(find.widgetWithText(DropdownButtonFormField<String>, 'Добавить преподавателя'), findsOneWidget);

    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Мария Петрова').last);
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(OutlinedButton, 'Добавить'));
    await pumpFrames(tester);

    expect(adapter.requestBodies, isEmpty); // PUT без тела
  });

  testWidgets('teacher не видит кнопок изменения состава и удаления', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson(teacherIds: const ['te1'])]),
      'GET /institutions/inst-1/teachers': (o, b) async =>
          jsonResponse(200, [memberJson(userId: 'te1', displayName: 'Мария Петрова')]),
      'GET /institutions/inst-1/students?group_id=g1': (o, b) async =>
          jsonResponse(200, [studentJson(userId: 's1', displayName: 'Оля Сидорова', groupIds: const ['g1'])]),
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'g1'), adapter: adapter, session: teacherSession());

    expect(find.text('Мария Петрова'), findsOneWidget);
    expect(find.text('Оля Сидорова'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Убрать'), findsNothing);
    expect(find.widgetWithText(OutlinedButton, 'Удалить группу'), findsNothing);
    expect(find.widgetWithText(TextField, 'Название'), findsNothing);
  });

  testWidgets('удаление группы: отмена не шлёт запрос, подтверждение шлёт DELETE', (tester) async {
    var deleted = false;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson()]),
      'GET /institutions/inst-1/teachers': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/students?group_id=g1': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, <Object>[]),
      'DELETE /institutions/inst-1/groups/g1': (o, b) async {
        deleted = true;
        return jsonResponse(204, '');
      },
    });

    await pumpScreen(tester, const GroupScreen(groupId: 'g1'), adapter: adapter, session: adminSession());

    await tester.tap(find.widgetWithText(OutlinedButton, 'Удалить группу'));
    await tester.pumpAndSettle();
    expect(find.text('Удалить группу?'), findsOneWidget);

    await tester.tap(find.text('Отмена'));
    await tester.pumpAndSettle();
    expect(deleted, isFalse);

    await tester.tap(find.widgetWithText(OutlinedButton, 'Удалить группу'));
    await tester.pumpAndSettle();
    await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Удалить')));
    await tester.pumpAndSettle();
    await pumpFrames(tester);

    expect(deleted, isTrue);
  });
}
