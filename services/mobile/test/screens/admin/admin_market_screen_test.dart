import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/router/paths.dart';
import 'package:gamification_mobile/screens/admin/admin_market_screen.dart';
import 'package:gamification_mobile/ui/design_tokens.dart';
import 'package:go_router/go_router.dart';

import '../staff/staff_test_support.dart';

/// [AdminMarketScreen] уходит по вложенным путям через `context.push` —
/// нужен настоящий `GoRouter`, а не голый `MaterialApp` (как в
/// `pumpScreen` из `staff_test_support.dart`).
Future<ProviderContainer> _pumpWithRouter(
  WidgetTester tester, {
  required RecordingAdapter adapter,
  required SessionState session,
}) async {
  final container = ProviderContainer(
    overrides: [
      sessionProvider.overrideWith(() => FixedSessionNotifier(session)),
      apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
    ],
  );
  addTearDown(container.dispose);
  final router = GoRouter(
    initialLocation: marketPath,
    routes: [
      GoRoute(
        path: marketPath,
        builder: (context, state) => const AdminMarketScreen(),
        routes: [
          GoRoute(
            path: 'privileges',
            builder: (context, state) => const Scaffold(body: Text('PRIVILEGES-SCREEN')),
          ),
          GoRoute(
            path: 'purchases',
            builder: (context, state) => const Scaffold(body: Text('PURCHASES-SCREEN')),
          ),
        ],
      ),
    ],
  );
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(theme: buildAppTheme(), routerConfig: router),
    ),
  );
  await pumpFrames(tester);
  return container;
}

void main() {
  testWidgets('число заявок отображается рядом с «Заявки»', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [
        {
          'id': 'pu1',
          'privilege_id': 'p1',
          'title': 'Пропуск домашки',
          'price': 30,
          'status': 'pending',
          'created_at': '2026-09-01T10:00:00Z',
          'resolved_at': null,
          'user_id': 'u2',
          'user_name': 'Ученик',
        },
        {
          'id': 'pu2',
          'privilege_id': 'p1',
          'title': 'Пропуск домашки',
          'price': 30,
          'status': 'pending',
          'created_at': '2026-09-01T10:00:00Z',
          'resolved_at': null,
          'user_id': 'u3',
          'user_name': 'Ученик 2',
        },
      ]),
    });

    await _pumpWithRouter(tester, adapter: adapter, session: adminSession());

    expect(find.text('2'), findsOneWidget);
  });

  testWidgets('при ошибке счётчика бейдж скрыт', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(500, {'detail': 'BOOM'}),
    });

    await _pumpWithRouter(tester, adapter: adapter, session: adminSession());

    expect(find.byType(Badge), findsNothing);
  });

  testWidgets('«Каталог» открывает вложенный маршрут', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await _pumpWithRouter(tester, adapter: adapter, session: adminSession());
    await tester.tap(find.text('Каталог'));
    await tester.pumpAndSettle();

    expect(find.text('PRIVILEGES-SCREEN'), findsOneWidget);
  });

  testWidgets('«Заявки» открывает вложенный маршрут', (tester) async {
    final adapter = RecordingAdapter({
      'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, <Object>[]),
    });

    await _pumpWithRouter(tester, adapter: adapter, session: adminSession());
    await tester.tap(find.text('Заявки'));
    await tester.pumpAndSettle();

    expect(find.text('PURCHASES-SCREEN'), findsOneWidget);
  });
}
