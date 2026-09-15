import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/teacher_market_screen.dart';

import 'staff_test_support.dart';

Map<String, dynamic> _privilegeJson({
  String id = 'p1',
  String title = 'Пропуск домашки',
  String? description = 'Одна работа без сдачи',
  int price = 100,
  int? stock = 5,
  bool isActive = true,
}) => {
  'id': id,
  'title': title,
  'description': description,
  'price': price,
  'stock': stock,
  'is_active': isActive,
};

void main() {
  testWidgets('загрузка → данные, без баланса и кнопок покупки', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [_privilegeJson()]),
    });

    await pumpScreen(tester, const TeacherMarketScreen(), adapter: adapter, session: teacherSession());

    expect(find.text('Пропуск домашки'), findsOneWidget);
    expect(find.textContaining('Баланс'), findsNothing);
    expect(find.widgetWithText(OutlinedButton, 'Купить'), findsNothing);
    // Только каталог — ни один POST и ни один запрос `me/*` не отправлен.
    expect(adapter.requestBodies, isEmpty);
  });

  testWidgets('ошибка загрузки показывает «Повторить»', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async {
        attempt += 1;
        if (attempt == 1) return jsonResponse(500, {'detail': 'BOOM'});
        return jsonResponse(200, [_privilegeJson()]);
      },
    });

    await pumpScreen(tester, const TeacherMarketScreen(), adapter: adapter, session: teacherSession());
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await pumpFrames(tester);

    expect(find.text('Пропуск домашки'), findsOneWidget);
  });

  testWidgets('пустой каталог показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const TeacherMarketScreen(), adapter: adapter, session: teacherSession());

    expect(find.text('Учреждение ещё не добавило привилегии'), findsOneWidget);
  });
}
