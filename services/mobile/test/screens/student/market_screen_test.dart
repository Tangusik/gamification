import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/screens/student/market_screen.dart';
import 'package:gamification_mobile/ui/design_tokens.dart';

import 'test_support.dart';

/// Открыть диалог подтверждения покупки и подтвердить его — общий шаг для
/// нескольких сценариев ниже. Диалог даёт финальную анимацию, `pumpAndSettle`
/// здесь безопасен: спиннеров на экране на этот момент уже нет.
Future<void> _buyAndConfirm(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(OutlinedButton, 'Купить'));
  await tester.pumpAndSettle();
  await tester.tap(find.descendant(of: find.byType(AlertDialog), matching: find.text('Купить')));
  await tester.pumpAndSettle();
  await pumpFrames(tester);
}

void main() {
  testWidgets('пустой каталог показывает пустое состояние', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: 100)),
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, <Object>[]),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await pumpScreen(tester, const MarketScreen(), adapter: adapter);

    expect(find.text('Учреждение ещё не добавило привилегии'), findsOneWidget);
  });

  testWidgets('успешная покупка обновляет баланс', (tester) async {
    var balance = 100;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: balance)),
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [privilegeJson(price: 30)]),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/purchases': (o, b) async {
        balance -= 30;
        return jsonResponse(201, purchaseJson());
      },
    });

    await pumpScreen(tester, const MarketScreen(), adapter: adapter);
    expect(find.text('100'), findsOneWidget);

    await _buyAndConfirm(tester);

    expect(find.text('70'), findsOneWidget);
    expect(adapter.requestBodies, hasLength(1));

    // Успех очищает попытку — следующая покупка идёт с новым operation_id.
    await _buyAndConfirm(tester);
    expect(adapter.requestBodies, hasLength(2));
    expect(adapter.requestBodies[0]['operation_id'], isNot(adapter.requestBodies[1]['operation_id']));
  });

  testWidgets(
    'сетевая ошибка, пересборка экрана в том же контейнере, повтор — один и тот же operation_id',
    (tester) async {
      var attempt = 0;
      final adapter = RecordingAdapter({
        'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: 100)),
        'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [privilegeJson(price: 30)]),
        'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
        'POST /institutions/inst-1/purchases': (o, b) async {
          attempt += 1;
          if (attempt == 1) {
            throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
          }
          return jsonResponse(201, purchaseJson());
        },
      });

      final container = ProviderContainer(
        overrides: [
          sessionProvider.overrideWith(() => FixedSessionNotifier(studentSession())),
          apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
        ],
      );
      addTearDown(container.dispose);

      Future<void> mountMarket() async {
        await tester.pumpWidget(
          UncontrolledProviderScope(
            container: container,
            child: MaterialApp(theme: buildAppTheme(), home: const MarketScreen()),
          ),
        );
        await pumpFrames(tester);
      }

      await mountMarket();
      await _buyAndConfirm(tester);
      expect(find.textContaining('Сервер недоступен'), findsOneWidget);

      // Экран уничтожается вместе со своим `State` — так бывает при redirect
      // на вход после 401, на `/institutions`, на `/password`, при смене
      // роли. `ProviderContainer` (и провайдер попыток покупки в нём) при
      // этом переживает пересборку — токен просто истёк, процесс жив.
      await tester.pumpWidget(
        UncontrolledProviderScope(container: container, child: const MaterialApp(home: SizedBox.shrink())),
      );
      await pumpFrames(tester);

      await mountMarket();
      await _buyAndConfirm(tester);

      expect(adapter.requestBodies, hasLength(2));
      expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
    },
  );

  testWidgets('сетевая ошибка и повтор уходят с одним operation_id', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: 100)),
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [privilegeJson(price: 30)]),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/purchases': (o, b) async {
        attempt += 1;
        if (attempt == 1) {
          throw DioException(requestOptions: o, type: DioExceptionType.connectionError);
        }
        return jsonResponse(201, purchaseJson());
      },
    });

    await pumpScreen(tester, const MarketScreen(), adapter: adapter);

    await _buyAndConfirm(tester);
    expect(find.textContaining('Сервер недоступен'), findsOneWidget);

    await _buyAndConfirm(tester);

    expect(adapter.requestBodies, hasLength(2));
    expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
  });

  testWidgets('PRICE_CHANGED даёт новый operation_id и показывает текст', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: 100)),
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [privilegeJson(price: 30)]),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/purchases': (o, b) async {
        attempt += 1;
        if (attempt == 1) {
          return jsonResponse(409, {'detail': 'PRICE_CHANGED'});
        }
        return jsonResponse(201, purchaseJson());
      },
    });

    await pumpScreen(tester, const MarketScreen(), adapter: adapter);

    await _buyAndConfirm(tester);
    expect(find.textContaining('Цена изменилась'), findsOneWidget);

    await _buyAndConfirm(tester);

    expect(adapter.requestBodies, hasLength(2));
    expect(adapter.requestBodies[0]['operation_id'], isNot(adapter.requestBodies[1]['operation_id']));
  });

  testWidgets('INSUFFICIENT_BALANCE и OUT_OF_STOCK показывают тексты сервера', (tester) async {
    var attempt = 0;
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/me/currency': (o, b) async => jsonResponse(200, currencyAccountJson(balance: 100)),
      'GET /institutions/inst-1/privileges': (o, b) async => jsonResponse(200, [privilegeJson(price: 30)]),
      'GET /institutions/inst-1/me/purchases': (o, b) async => jsonResponse(200, <Object>[]),
      'POST /institutions/inst-1/purchases': (o, b) async {
        attempt += 1;
        if (attempt == 1) {
          return jsonResponse(409, {'detail': 'INSUFFICIENT_BALANCE'});
        }
        return jsonResponse(409, {'detail': 'OUT_OF_STOCK'});
      },
    });

    await pumpScreen(tester, const MarketScreen(), adapter: adapter);

    await _buyAndConfirm(tester);
    expect(find.textContaining('Недостаточно средств'), findsOneWidget);

    await _buyAndConfirm(tester);
    expect(find.textContaining('Позиция закончилась'), findsOneWidget);

    // Оба отказа сохраняют id — сервер мог уже увидеть попытку.
    expect(adapter.requestBodies[0]['operation_id'], adapter.requestBodies[1]['operation_id']);
  });
}
