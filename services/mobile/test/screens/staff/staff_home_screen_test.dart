import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/staff_home_screen.dart';

import 'staff_test_support.dart';

Map<String, dynamic> _purchaseJson({String id = 'pu1', String status = 'pending'}) => {
  'id': id,
  'privilege_id': 'p1',
  'title': 'Пропуск домашки',
  'price': 30,
  'status': status,
  'created_at': '2026-09-01T10:00:00Z',
  'resolved_at': null,
  'user_id': 'u2',
  'user_name': 'Оля Ученикова',
};

Map<String, dynamic> _groupJson({String id = 'g1', String name = 'Группа А', int studentsCount = 3}) => {
  'id': id,
  'name': name,
  'teacher_ids': const <String>[],
  'students_count': studentsCount,
};

void main() {
  group('admin', () {
    testWidgets('показывает число заявок и ссылку «Все заявки»', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/purchases?status=pending': (o, b) async =>
            jsonResponse(200, [_purchaseJson(), _purchaseJson(id: 'pu2')]),
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: adminSession());

      expect(find.text('Заявки на выдачу: 2'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Все заявки'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Начислить валюту'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Пригласить ученика'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Добавить преподавателя'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Создать группу'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Добавить привилегию'), findsOneWidget);
    });

    testWidgets('сетевая ошибка показывает «Повторить»', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/purchases?status=pending': (o, b) async {
          throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
        },
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: adminSession());

      expect(find.widgetWithText(OutlinedButton, 'Повторить'), findsOneWidget);
    });

    testWidgets('нет заявок — счётчик показывает 0', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, <Object>[]),
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: adminSession());

      expect(find.text('Заявки на выдачу: 0'), findsOneWidget);
    });
  });

  group('teacher', () {
    testWidgets('показывает свои группы с числом учеников', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [_groupJson()]),
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: teacherSession());

      expect(find.text('Группа А'), findsOneWidget);
      expect(find.text('учеников: 3'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Начислить валюту'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Пригласить ученика'), findsOneWidget);
      expect(find.widgetWithText(OutlinedButton, 'Добавить преподавателя'), findsNothing);
    });

    testWidgets('пустой список групп показывает текст веба', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: teacherSession());

      expect(
        find.text('В ваших группах нет учеников. Состав групп задаёт администратор'),
        findsOneWidget,
      );
    });

    testWidgets('сетевая ошибка показывает «Повторить»', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/groups': (o, b) async {
          throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
        },
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: teacherSession());

      expect(find.widgetWithText(OutlinedButton, 'Повторить'), findsOneWidget);
    });

    testWidgets('teacher не отправляет запрос заявок', (tester) async {
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, <Object>[]),
      });

      await pumpScreen(tester, const StaffHomeScreen(), adapter: adapter, session: teacherSession());

      // Если бы экран всё же дёрнул заявки, RecordingAdapter бросил бы
      // StateError «Нет фейкового обработчика» и pumpScreen упал бы.
      expect(find.text('ЗАЯВКИ'), findsNothing);
    });
  });
}
