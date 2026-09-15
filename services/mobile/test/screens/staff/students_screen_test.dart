import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/students_screen.dart';

import 'staff_test_support.dart';

Map<String, dynamic> _groupJson({String id = 'g1', String name = 'Группа А', List<String> teacherIds = const []}) => {
  'id': id,
  'name': name,
  'teacher_ids': teacherIds,
  'students_count': 1,
};

Map<String, dynamic> _studentJson({
  String userId = 'u2',
  String? displayName = 'Оля Ученикова',
  String status = 'active',
  List<String> groupIds = const [],
  int balance = 120,
}) => {
  'user_id': userId,
  'display_name': displayName,
  'status': status,
  'created_at': '2026-01-01T00:00:00Z',
  'group_ids': groupIds,
  'balance': balance,
};

void main() {
  testWidgets('загрузка → список учеников с балансом', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, [_studentJson()]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Оля Ученикова'), findsOneWidget);
    expect(find.text('120'), findsOneWidget);
  });

  testWidgets('сетевая ошибка показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async {
        throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
      },
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());

    expect(find.widgetWithText(OutlinedButton, 'Повторить'), findsOneWidget);
  });

  testWidgets('пустой список — admin видит действие «Создать ссылку-приглашение»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Учеников пока нет.'), findsOneWidget);
    expect(find.widgetWithText(OutlinedButton, 'Создать ссылку-приглашение'), findsOneWidget);
  });

  testWidgets('пустой список — teacher видит текст без действия', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: teacherSession());

    expect(
      find.text('В ваших группах нет учеников. Состав групп задаёт администратор.'),
      findsOneWidget,
    );
    expect(find.widgetWithText(OutlinedButton, 'Создать ссылку-приглашение'), findsNothing);
  });

  testWidgets('display_name = null — admin видит «Задать имя»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, [_studentJson(displayName: null)]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });
    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());
    expect(find.text('Задать имя'), findsOneWidget);
  });

  testWidgets('display_name = null — teacher видит «Без имени»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, [_studentJson(displayName: null)]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });
    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: teacherSession());
    expect(find.text('Без имени'), findsOneWidget);
  });

  testWidgets('UUID ученика не выводится на экран', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, [_studentJson(userId: 'u2')]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('u2'), findsNothing);
  });

  testWidgets('поиск по имени сужает список', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, [
            _studentJson(userId: 'u2', displayName: 'Оля Ученикова'),
            _studentJson(userId: 'u3', displayName: 'Петя Петров'),
          ]),
      'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [_groupJson()]),
    });

    await pumpScreen(tester, const StudentsScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Оля Ученикова'), findsOneWidget);
    expect(find.text('Петя Петров'), findsOneWidget);

    await tester.enterText(find.widgetWithText(TextField, 'Поиск по имени'), 'Оля');
    await pumpFrames(tester, 2);

    expect(find.text('Оля Ученикова'), findsOneWidget);
    expect(find.text('Петя Петров'), findsNothing);
  });
}
