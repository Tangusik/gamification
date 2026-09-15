import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/token_storage.dart';

import '../../auth/test_support.dart';
import 'test_harness.dart';

void main() {
  testWidgets('без активных членств — пусто и форма создания учреждения', (tester) async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);

    await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      'GET /institutions': (o) async => jsonResponse(200, <Object>[]),
    });

    expect(find.text('Мои учреждения'), findsWidgets);
    expect(find.text('Создайте учреждение или откройте ссылку-приглашение от школы.'), findsOneWidget);
    expect(find.widgetWithText(TextField, 'Название учреждения'), findsOneWidget);
  });

  testWidgets('создание учреждения выбирает его текущим', (tester) async {
    final token = fakeJwt({'sub': 'u1', 'exp': unixSecondsFromNow(const Duration(minutes: 15))});
    final storage = InMemoryTokenStorage();
    await storage.writeToken(token);

    var tokenRequested = false;
    var created = false;
    final selectedToken = fakeJwt({
      'sub': 'u1',
      'institution_id': 'inst-9',
      'exp': unixSecondsFromNow(const Duration(minutes: 15)),
    });

    await pumpTestApp(tester, storage, {
      'GET /users/me': (o) async => jsonResponse(200, userJson()),
      // До создания членств нет, после — новое учреждение с ролью создателя.
      'GET /institutions': (o) async => jsonResponse(
        200,
        created ? [membershipJson(institutionId: 'inst-9', name: 'Школа радости', role: 'admin')] : <Object>[],
      ),
      'POST /institutions': (o) async {
        created = true;
        return jsonResponse(201, {'id': 'inst-9'});
      },
      'POST /institutions/inst-9/token': (o) async {
        tokenRequested = true;
        return jsonResponse(200, tokenJson(selectedToken));
      },
    });
    expect(find.text('Мои учреждения'), findsWidgets);

    await tester.enterText(find.widgetWithText(TextField, 'Название учреждения'), 'Школа радости');
    await tapAndSettle(tester, find.text('Создать учреждение'));

    expect(tokenRequested, isTrue);
    expect(await storage.readLastInstitutionId(), 'inst-9');
    // Без перечитывания членств контекст оставался пустым, и роутер
    // возвращал на онбординг — пользователь застревал на этом экране.
    expect(find.text('Создайте учреждение или откройте ссылку-приглашение от школы.'), findsNothing);
  });
}
