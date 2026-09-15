import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/admin/privileges_screen.dart';

import '../staff/staff_test_support.dart';

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

/// `find.text` считает совпадением и `EditableText` c таким же содержимым
/// (значение соседнего поля правки может случайно совпасть с заголовком
/// карточки) — там, где важно количество карточек, ищем заголовок точечно.
Finder _cardTitle(String text) => find.widgetWithText(Card, text).first;

TextEditingController _controllerFor(WidgetTester tester, String label) {
  final field = tester.widget<TextField>(find.widgetWithText(TextField, label).first);
  return field.controller!;
}

void main() {
  testWidgets('загрузка → данные', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [_privilegeJson()]),
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    expect(_cardTitle('Пропуск домашки'), findsOneWidget);
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

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());
    expect(find.text('Повторить'), findsOneWidget);

    await tester.tap(find.text('Повторить'));
    await pumpFrames(tester);

    expect(_cardTitle('Пропуск домашки'), findsOneWidget);
  });

  testWidgets('пустой каталог показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    expect(find.text('Позиций пока нет'), findsOneWidget);
  });

  testWidgets('создание с 422 показывает ошибку у поля и не сбрасывает форму', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/privileges': (o, b) async => jsonResponse(422, {
        'detail': [
          {
            'loc': ['body', 'price'],
            'msg': 'Цена должна быть положительной',
          },
        ],
      }),
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Название'), 'Новая позиция');
    await tester.enterText(find.widgetWithText(TextField, 'Цена (в «коины»)'), '0');
    await tester.tap(find.text('Добавить позицию'));
    await pumpFrames(tester);

    expect(find.text('Цена должна быть положительной'), findsOneWidget);
    expect(_controllerFor(tester, 'Название').text, 'Новая позиция');
  });

  testWidgets('успешное создание очищает форму и добавляет позицию в список', (tester) async {
    var privileges = <Map<String, dynamic>>[];
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, privileges),
      'POST /institutions/inst-1/privileges': (o, b) async {
        final created = _privilegeJson(id: 'p2', title: 'Кофе с директором', price: 50, stock: null);
        privileges = [...privileges, created];
        return jsonResponse(201, created);
      },
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    await tester.enterText(find.widgetWithText(TextField, 'Название'), 'Кофе с директором');
    await tester.enterText(find.widgetWithText(TextField, 'Цена (в «коины»)'), '50');
    await tester.tap(find.text('Добавить позицию'));
    await pumpFrames(tester);

    expect(find.text('Сохранено'), findsOneWidget);
    expect(_cardTitle('Кофе с директором'), findsOneWidget);
    // Форма создания очищена — поле «Название» снова пустое.
    expect(_controllerFor(tester, 'Название').text, isEmpty);
  });

  testWidgets('скрыть позицию сохраняется без подтверждения', (tester) async {
    await tester.binding.setSurfaceSize(const Size(800, 2000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var isActive = true;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async =>
          jsonResponse(200, [_privilegeJson(isActive: isActive)]),
      'PATCH /institutions/inst-1/privileges/p1': (o, b) async {
        isActive = b is Map && b['is_active'] == false ? false : isActive;
        return jsonResponse(200, _privilegeJson(isActive: isActive));
      },
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    await tester.tap(find.byType(CheckboxListTile).last);
    await pumpFrames(tester, 1);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Сохранить'));
    await pumpFrames(tester);

    expect(find.byType(AlertDialog), findsNothing);
    expect(find.text('Скрыта'), findsOneWidget);
  });

  testWidgets('правка цены отправляет только изменившиеся поля', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [_privilegeJson()]),
      'PATCH /institutions/inst-1/privileges/p1': (o, b) async =>
          jsonResponse(200, _privilegeJson(price: 200)),
    });

    await pumpScreen(tester, const PrivilegesScreen(), adapter: adapter, session: adminSession());

    final priceField = find.widgetWithText(TextField, 'Цена (в «коины»)').last;
    await tester.dragUntilVisible(priceField, find.byType(ListView), const Offset(0, -300));
    await tester.enterText(priceField, '200');

    final saveButton = find.widgetWithText(OutlinedButton, 'Сохранить');
    await tester.dragUntilVisible(saveButton, find.byType(ListView), const Offset(0, -300));
    await tester.tap(saveButton);
    await pumpFrames(tester);

    expect(adapter.requestBodies, hasLength(1));
    expect(adapter.requestBodies.single, {'price': 200});
    expect(find.text('Сохранено'), findsOneWidget);
  });
}
