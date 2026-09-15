// Тесты `GroupsScreen` — загрузка/ошибка/пусто, создание (только admin) и
// разграничение ролей: teacher не видит и не может вызвать форму создания.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/groups_screen.dart';

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

void main() {
  testWidgets('загрузка сменяется данными', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson()]),
    });

    await pumpScreen(tester, const GroupsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('9 «А»'), findsOneWidget);
  });

  testWidgets('ошибка списка показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(500, {'detail': 'boom'}),
    });

    await pumpScreen(tester, const GroupsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Повторить'), findsOneWidget);
  });

  testWidgets('пустой список показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const GroupsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Групп пока нет.'), findsOneWidget);
  });

  testWidgets('admin видит форму создания и может создать группу', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/groups': (o, b) async => jsonResponse(201, groupJson(name: 'Новая группа')),
    });

    await pumpScreen(tester, const GroupsScreen(), adapter: adapter, session: adminSession());

    expect(find.widgetWithText(TextField, 'Название группы'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, 'Название группы'), 'Новая группа');
    await tester.tap(find.widgetWithText(OutlinedButton, 'Создать группу'));
    await pumpFrames(tester);

    expect(adapter.requestBodies, hasLength(1));
    expect(adapter.requestBodies.first['name'], 'Новая группа');
  });

  testWidgets('teacher не видит форму создания', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [groupJson()]),
    });

    await pumpScreen(tester, const GroupsScreen(), adapter: adapter, session: teacherSession());

    expect(find.widgetWithText(TextField, 'Название группы'), findsNothing);
    expect(find.widgetWithText(OutlinedButton, 'Создать группу'), findsNothing);
    // Данные всё равно доступны для чтения.
    expect(find.text('9 «А»'), findsOneWidget);
  });
}
