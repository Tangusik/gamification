import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/staff/student_card_screen.dart';

import 'staff_test_support.dart';

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

Map<String, dynamic> _transactionJson({
  String id = 't1',
  String kind = 'manual_accrual',
  int amount = 10,
  String? comment,
  String? createdByName = 'Иван Иванов',
  String createdByRole = 'teacher',
  String createdAt = '2026-09-01T10:00:00Z',
  String? reversesId,
}) => {
  'id': id,
  'kind': kind,
  'amount': amount,
  'comment': comment,
  'created_by_name': createdByName,
  'created_by_role': createdByRole,
  'created_at': createdAt,
  'reverses_id': reversesId,
};

Map<String, dynamic> _accountJson({int balance = 120, List<Map<String, dynamic>> transactions = const []}) => {
  'balance': balance,
  'transactions': transactions,
};

Map<String, dynamic> _purchaseJson({String id = 'pu1', String status = 'fulfilled'}) => {
  'id': id,
  'privilege_id': 'p1',
  'title': 'Пропуск домашки',
  'price': 30,
  'status': status,
  'created_at': '2026-09-01T10:00:00Z',
  'resolved_at': null,
};

typedef _Handler = Future<ResponseBody> Function(RequestOptions, Object?);

/// Роуты, общие большинству тестов: список учеников и история операций.
/// [extraRoutes] переопределяет/дополняет базовый набор — так тест задаёт
/// свой обработчик начисления/сторно/групп, не пересобирая всё остальное.
RecordingAdapter _baseAdapter({
  List<Object> students = const [],
  Object? account,
  Object? purchases,
  Map<String, _Handler> extraRoutes = const {},
}) {
  final routes = <String, _Handler>{
    'GET /institutions/inst-1/students': (o, b) async => jsonResponse(200, students),
    'GET /institutions/inst-1/students/u2/currency-transactions': (o, b) async =>
        jsonResponse(200, account ?? _accountJson()),
  };
  if (purchases != null) {
    routes['GET /institutions/inst-1/purchases?user_id=u2'] = (o, b) async => jsonResponse(200, purchases);
  }
  routes.addAll(extraRoutes);
  return RecordingAdapter(routes);
}

/// Нажать «Сторно» у операции, подтвердить диалог «Сторнировать».
Future<void> _reverseAndConfirm(WidgetTester tester) async {
  final trigger = find.widgetWithText(TextButton, 'Сторно');
  await tester.ensureVisible(trigger);
  await tester.pumpAndSettle();
  await tester.tap(trigger);
  await tester.pumpAndSettle();
  await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Сторнировать')));
  await tester.pumpAndSettle();
  await pumpFrames(tester);
}

/// Прокрутить кнопку в зону видимости (форма ниже секций редактирования
/// может уйти за пределы окна теста) и нажать её.
Future<void> _tapScrolled(WidgetTester tester, Finder finder) async {
  await tester.ensureVisible(finder);
  await tester.tap(finder);
}


void main() {
  testWidgets('admin: загрузка → имя, статус, группы, баланс, покупки', (tester) async {
    final adapter = _baseAdapter(
      students: [
        _studentJson(groupIds: const ['g1']),
      ],
      account: _accountJson(balance: 120, transactions: [_transactionJson()]),
      purchases: [_purchaseJson()],
      extraRoutes: {
        'GET /institutions/inst-1/groups': (o, b) async => jsonResponse(200, [
              {'id': 'g1', 'name': 'Группа А', 'teacher_ids': <String>[], 'students_count': 1},
            ]),
      },
    );

    await pumpScreen(
      tester,
      const StudentCardScreen(userId: 'u2'),
      adapter: adapter,
      session: adminSession(),
    );

    expect(find.widgetWithText(TextField, 'Имя'), findsOneWidget);
    expect(find.text('Группа А'), findsOneWidget);
    expect(find.text('120'), findsWidgets);
    expect(find.text('Пропуск домашки'), findsOneWidget);
  });

  testWidgets('сетевая ошибка списка учеников показывает «Повторить»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async {
        throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
      },
    });

    await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

    expect(find.widgetWithText(OutlinedButton, 'Повторить'), findsOneWidget);
  });

  testWidgets('ученик не найден в списке — понятное сообщение', (tester) async {
    final adapter = _baseAdapter(students: const []);

    await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

    expect(find.text('Ученик не найден.'), findsOneWidget);
  });

  testWidgets('403 от сервера показывается как ошибка, а не падение', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/students': (o, b) async => jsonResponse(403, {'detail': 'INSUFFICIENT_ROLE'}),
    });

    await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: teacherSession());

    expect(find.textContaining('Недостаточно прав'), findsOneWidget);
  });

  group('роли', () {
    testWidgets('teacher не видит сторно, правку имени/статуса и покупки', (tester) async {
      final adapter = _baseAdapter(
        students: [_studentJson()],
        account: _accountJson(transactions: [_transactionJson()]),
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: teacherSession());

      expect(find.widgetWithText(TextField, 'Имя'), findsNothing);
      expect(find.byType(DropdownButton<Object?>), findsNothing);
      expect(find.widgetWithText(TextButton, 'Сторно'), findsNothing);
      expect(find.text('Покупки'), findsNothing);
      // Если бы экран всё же дёрнул покупки, RecordingAdapter бросил бы
      // StateError «Нет фейкового обработчика» и pumpScreen упал бы —
      // отсутствие маршрута в _baseAdapter здесь уже само по себе проверка.
    });

    testWidgets('admin видит правку имени/статуса, сторно и покупки', (tester) async {
      final adapter = _baseAdapter(
        students: [_studentJson()],
        account: _accountJson(transactions: [_transactionJson()]),
        purchases: const [],
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

      expect(find.widgetWithText(TextField, 'Имя'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Сторно'), findsOneWidget);
      expect(find.text('Покупки'), findsOneWidget);
    });

    testWidgets('сторнированное начисление не показывает кнопку «Сторно» повторно', (tester) async {
      final adapter = _baseAdapter(
        students: [_studentJson()],
        account: _accountJson(
          transactions: [
            _transactionJson(id: 't1', amount: 10),
            _transactionJson(id: 't2', kind: 'reversal', amount: -10, reversesId: 't1'),
          ],
        ),
        purchases: const [],
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

      expect(find.widgetWithText(TextButton, 'Сторно'), findsNothing);
    });
  });

  group('начисление', () {
    testWidgets('успех очищает форму, показывает «Сохранено» и даёт новый operation_id', (tester) async {
      final adapter = _baseAdapter(
        students: [_studentJson()],
        extraRoutes: {
          'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async =>
              jsonResponse(201, _transactionJson()),
        },
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: teacherSession());

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);

      expect(find.text('Сохранено'), findsOneWidget);
      expect(find.widgetWithText(TextFormField, 'Сумма'), findsOneWidget);
      final sumField = tester.widget<TextFormField>(find.widgetWithText(TextFormField, 'Сумма'));
      expect(sumField.controller!.text, isEmpty);
      expect(sumField.enabled, isTrue);

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '20');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);

      expect(adapter.requestBodies, hasLength(2));
      expect(adapter.requestBodies[0]['operation_id'], isNot(adapter.requestBodies[1]['operation_id']));
    });

    testWidgets(
      'сетевая ошибка, пересборка экрана, повтор — тот же operation_id',
      (tester) async {
        var attempt = 0;
        final adapter = _baseAdapter(
          students: [_studentJson()],
          extraRoutes: {
            'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
              attempt += 1;
              if (attempt == 1) {
                throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
              }
              return jsonResponse(201, _transactionJson());
            },
          },
        );

        const screen = StudentCardScreen(userId: 'u2');
        final container = await pumpScreen(tester, screen, adapter: adapter, session: teacherSession());

        await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
        await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
        await pumpFrames(tester);
        expect(find.textContaining('Сервер недоступен'), findsOneWidget);

        await remountScreen(tester, container, screen);
        await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
        await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
        await pumpFrames(tester);

        expect(adapter.requestBodies, hasLength(2));
        expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
      },
    );

    testWidgets(
      'сетевая ошибка блокирует поля отправленными значениями, повтор — то же тело',
      (tester) async {
        var attempt = 0;
        final adapter = _baseAdapter(
          students: [_studentJson()],
          extraRoutes: {
            'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
              attempt += 1;
              if (attempt == 1) {
                throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
              }
              return jsonResponse(201, _transactionJson());
            },
          },
        );

        await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: teacherSession());

        await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
        await tester.enterText(find.widgetWithText(TextFormField, 'Комментарий (необязательно)'), 'за домашку');
        await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
        await pumpFrames(tester);

        expect(find.textContaining('Сервер недоступен'), findsOneWidget);
        expect(find.textContaining('не подтверждено'), findsOneWidget);
        var sumField = tester.widget<TextFormField>(find.widgetWithText(TextFormField, 'Сумма'));
        expect(sumField.enabled, isFalse);
        expect(sumField.controller!.text, '50');
        var commentField = tester.widget<TextFormField>(
          find.widgetWithText(TextFormField, 'Комментарий (необязательно)'),
        );
        expect(commentField.enabled, isFalse);
        expect(commentField.controller!.text, 'за домашку');

        await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
        await pumpFrames(tester);

        expect(adapter.requestBodies, hasLength(2));
        expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
        expect(adapter.requestBodies[1]['amount'], 50);
        expect(adapter.requestBodies[1]['comment'], 'за домашку');
        expect(find.text('Сохранено'), findsOneWidget);
        sumField = tester.widget<TextFormField>(find.widgetWithText(TextFormField, 'Сумма'));
        expect(sumField.enabled, isTrue);
        expect(sumField.controller!.text, isEmpty);
      },
    );

    testWidgets(
      'сетевая ошибка, пересборка экрана — поля снова заполнены и заблокированы',
      (tester) async {
        final adapter = _baseAdapter(
          students: [_studentJson()],
          extraRoutes: {
            'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
              throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
            },
          },
        );

        const screen = StudentCardScreen(userId: 'u2');
        final container = await pumpScreen(tester, screen, adapter: adapter, session: teacherSession());

        await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
        await tester.enterText(find.widgetWithText(TextFormField, 'Комментарий (необязательно)'), 'за домашку');
        await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
        await pumpFrames(tester);
        expect(find.textContaining('Сервер недоступен'), findsOneWidget);

        await remountScreen(tester, container, screen);

        expect(find.textContaining('не подтверждено'), findsOneWidget);
        final sumField = tester.widget<TextFormField>(find.widgetWithText(TextFormField, 'Сумма'));
        expect(sumField.enabled, isFalse);
        expect(sumField.controller!.text, '50');
        final commentField = tester.widget<TextFormField>(
          find.widgetWithText(TextFormField, 'Комментарий (необязательно)'),
        );
        expect(commentField.enabled, isFalse);
        expect(commentField.controller!.text, 'за домашку');
        expect(adapter.requestBodies, hasLength(1));
      },
    );

    testWidgets('OPERATION_ID_CONFLICT даёт новый operation_id', (tester) async {
      var attempt = 0;
      final adapter = _baseAdapter(
        students: [_studentJson()],
        extraRoutes: {
          'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
            attempt += 1;
            if (attempt == 1) {
              return jsonResponse(409, {'detail': 'OPERATION_ID_CONFLICT'});
            }
            return jsonResponse(201, _transactionJson());
          },
        },
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: teacherSession());

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);
      expect(find.textContaining('уже прошло с другими данными'), findsOneWidget);
      // Явный текст локальный для экрана — общий messageForError на этот
      // код даёт другую формулировку, здесь она не должна показываться.
      expect(find.textContaining('Обновите экран'), findsNothing);

      final sumField = tester.widget<TextFormField>(find.widgetWithText(TextFormField, 'Сумма'));
      expect(sumField.enabled, isTrue);

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);

      expect(adapter.requestBodies, hasLength(2));
      expect(adapter.requestBodies[0]['operation_id'], isNot(adapter.requestBodies[1]['operation_id']));
    });

    testWidgets('STUDENT_SUSPENDED сохраняет operation_id (не однозначный исход)', (tester) async {
      var attempt = 0;
      final adapter = _baseAdapter(
        students: [_studentJson(status: 'suspended')],
        extraRoutes: {
          'POST /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
            attempt += 1;
            if (attempt == 1) {
              return jsonResponse(409, {'detail': 'STUDENT_SUSPENDED'});
            }
            return jsonResponse(201, _transactionJson());
          },
        },
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);
      expect(find.textContaining('приостановлено'), findsOneWidget);

      await tester.enterText(find.widgetWithText(TextFormField, 'Сумма'), '50');
      await _tapScrolled(tester, find.widgetWithText(OutlinedButton, 'Начислить'));
      await pumpFrames(tester);

      expect(adapter.requestBodies, hasLength(2));
      expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
    });
  });

  group('сторно', () {
    testWidgets('успех перечитывает историю, показывает «Сохранено» и даёт новый operation_id', (tester) async {
      var reversed = false;
      final adapter = _baseAdapter(
        students: [_studentJson()],
        purchases: const [],
        extraRoutes: {
          'GET /institutions/inst-1/students/u2/currency-transactions': (o, b) async {
            if (!reversed) return jsonResponse(200, _accountJson(transactions: [_transactionJson(id: 't1')]));
            return jsonResponse(
              200,
              _accountJson(
                transactions: [
                  _transactionJson(id: 't1'),
                  _transactionJson(id: 't2', kind: 'reversal', amount: -10, reversesId: 't1'),
                ],
              ),
            );
          },
          'POST /institutions/inst-1/currency-transactions/t1/reversal': (o, b) async {
            reversed = true;
            return jsonResponse(201, _transactionJson(id: 't2', kind: 'reversal', amount: -10, reversesId: 't1'));
          },
        },
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

      await _reverseAndConfirm(tester);

      expect(find.text('Сохранено'), findsOneWidget);
      expect(find.widgetWithText(TextButton, 'Сторно'), findsNothing);
    });

    testWidgets(
      'сетевая ошибка, пересборка экрана, повтор — тот же operation_id',
      (tester) async {
        var attempt = 0;
        final adapter = _baseAdapter(
          students: [_studentJson()],
          account: _accountJson(transactions: [_transactionJson(id: 't1')]),
          purchases: const [],
          extraRoutes: {
            'POST /institutions/inst-1/currency-transactions/t1/reversal': (o, b) async {
              attempt += 1;
              if (attempt == 1) {
                throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
              }
              return jsonResponse(201, _transactionJson(id: 't2', kind: 'reversal', amount: -10, reversesId: 't1'));
            },
          },
        );

        const screen = StudentCardScreen(userId: 'u2');
        final container = await pumpScreen(tester, screen, adapter: adapter, session: adminSession());

        await _reverseAndConfirm(tester);
        expect(find.textContaining('Сервер недоступен'), findsOneWidget);

        await remountScreen(tester, container, screen);
        await _reverseAndConfirm(tester);

        expect(adapter.requestBodies, hasLength(2));
        expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
      },
    );

    testWidgets('TRANSACTION_ALREADY_REVERSED даёт новый operation_id при следующей попытке', (tester) async {
      final adapter = _baseAdapter(
        students: [_studentJson()],
        account: _accountJson(transactions: [_transactionJson(id: 't1')]),
        purchases: const [],
        extraRoutes: {
          'POST /institutions/inst-1/currency-transactions/t1/reversal': (o, b) async =>
              jsonResponse(409, {'detail': 'TRANSACTION_ALREADY_REVERSED'}),
        },
      );

      await pumpScreen(tester, const StudentCardScreen(userId: 'u2'), adapter: adapter, session: adminSession());

      await _reverseAndConfirm(tester);
      expect(find.textContaining('уже сторнировано'), findsOneWidget);
      expect(adapter.requestBodies, hasLength(1));
      final firstId = adapter.requestBodies[0]['operation_id'];

      // Повторное открытие диалога на той же (ещё не сторнированной по
      // мнению локального состояния) транзакции даёт новый id — старый
      // сброшен как однозначный исход.
      await _reverseAndConfirm(tester);
      expect(adapter.requestBodies, hasLength(2));
      expect(adapter.requestBodies[1]['operation_id'], isNot(firstId));
    });
  });
}
