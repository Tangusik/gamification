// Маршруты 09b/09c: проверка роли в билдере маршрута, состав вкладок по
// роли и бейдж счётчика заявок у admin.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/auth_api.dart' as auth_api;
import 'package:gamification_mobile/auth/session.dart';
import 'package:gamification_mobile/main.dart';
import 'package:gamification_mobile/router/app_router.dart';

import '../screens/staff/staff_test_support.dart';

class MutableSessionNotifier extends SessionNotifier {
  MutableSessionNotifier(this._initial);

  final SessionState _initial;

  @override
  SessionState build() => _initial;

  void setState(SessionState next) => state = next;
}

Future<void> _pumpFrames(WidgetTester tester, [int times = 20]) async {
  for (var i = 0; i < times; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

ProviderContainer _buildContainer(SessionState session, {Routes routes = const {}}) {
  final adapter = RecordingAdapter(routes);
  return ProviderContainer(
    overrides: [
      sessionProvider.overrideWith(() => FixedSessionNotifier(session)),
      apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
    ],
  );
}

Future<ProviderContainer> _pumpApp(WidgetTester tester, ProviderContainer container) async {
  addTearDown(container.dispose);
  await tester.pumpWidget(UncontrolledProviderScope(container: container, child: const MyApp()));
  await _pumpFrames(tester);
  return container;
}

void main() {
  group('teacher', () {
    testWidgets('не видит вкладки и пункты «Ещё» админа', (tester) async {
      final container = _buildContainer(teacherSession());
      await _pumpApp(tester, container);

      expect(find.text('Главная'), findsWidgets);
      expect(find.text('Ученики'), findsWidgets);
      expect(find.text('Преподаватели'), findsNothing);
      expect(find.text('Настройки учреждения'), findsNothing);
    });

    testWidgets('получает «нет доступа» на admin-путях', (tester) async {
      final container = _buildContainer(teacherSession());
      await _pumpApp(tester, container);

      for (final path in const ['/teachers', '/settings', '/market/privileges', '/market/purchases']) {
        container.read(goRouterProvider).go(path);
        await _pumpFrames(tester);
        expect(find.text('Нет доступа'), findsWidgets, reason: 'путь $path должен быть запрещён');
      }
    });

    testWidgets('видит маркет только на чтение', (tester) async {
      final container = _buildContainer(teacherSession());
      await _pumpApp(tester, container);

      container.read(goRouterProvider).go('/market');
      await _pumpFrames(tester);
      expect(find.text('Маркет'), findsWidgets);
    });
  });

  group('student', () {
    testWidgets('получает «нет доступа» на staff-маршрутах', (tester) async {
      final container = _buildContainer(studentSessionFor());
      await _pumpApp(tester, container);

      for (final path in const ['/students', '/groups', '/invitations', '/teachers', '/settings']) {
        container.read(goRouterProvider).go(path);
        await _pumpFrames(tester);
        expect(find.text('Нет доступа'), findsWidgets, reason: 'путь $path должен быть запрещён');
      }
    });
  });

  group('admin', () {
    testWidgets('открывает все заготовки', (tester) async {
      final container = _buildContainer(
        adminSession(),
        routes: {
          'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, <Object>[]),
          'GET /institutions/inst-1/purchases': (o, b) async => jsonResponse(200, <Object>[]),
        },
      );
      await _pumpApp(tester, container);

      expect(find.text('Главная'), findsWidgets);

      container.read(goRouterProvider).go('/students');
      await _pumpFrames(tester);
      expect(find.text('Ученики'), findsWidgets);

      container.read(goRouterProvider).go('/groups');
      await _pumpFrames(tester);
      expect(find.text('Группы'), findsWidgets);

      container.read(goRouterProvider).go('/invitations');
      await _pumpFrames(tester);
      expect(find.text('Приглашения'), findsWidgets);

      container.read(goRouterProvider).go('/teachers');
      await _pumpFrames(tester);
      expect(find.text('Преподаватели'), findsWidgets);

      container.read(goRouterProvider).go('/settings');
      await _pumpFrames(tester);
      expect(find.text('Настройки учреждения'), findsWidgets);

      container.read(goRouterProvider).go('/market/privileges');
      await _pumpFrames(tester);
      expect(find.text('Каталог'), findsWidgets);

      container.read(goRouterProvider).go('/market/purchases');
      await _pumpFrames(tester);
      expect(find.textContaining('Заявки'), findsWidgets);
    });

    testWidgets('видит бейдж заявок на вкладке «Маркет», если есть pending', (tester) async {
      final container = _buildContainer(
        adminSession(),
        routes: {
          'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(200, [
                {
                  'id': 'pu1',
                  'privilege_id': 'p1',
                  'title': 'Пропуск домашки',
                  'price': 100,
                  'status': 'pending',
                  'created_at': '2026-09-01T10:00:00Z',
                  'resolved_at': null,
                },
              ]),
        },
      );
      await _pumpApp(tester, container);

      expect(find.text('1'), findsWidgets);
    });

    testWidgets('бейдж скрыт при ошибке запроса счётчика', (tester) async {
      final container = _buildContainer(
        adminSession(),
        routes: {
          'GET /institutions/inst-1/purchases?status=pending': (o, b) async => jsonResponse(500, {'detail': 'boom'}),
        },
      );
      await _pumpApp(tester, container);

      expect(find.text('0'), findsNothing);
      expect(find.text('1'), findsNothing);
    });
  });

  testWidgets('смена роли в сессии перерисовывает главный экран', (tester) async {
    final notifier = MutableSessionNotifier(teacherSession());
    final adapter = RecordingAdapter(const {});
    final container = ProviderContainer(
      overrides: [
        sessionProvider.overrideWith(() => notifier),
        apiClientProvider.overrideWithValue(buildFakeApiClient(adapter)),
      ],
    );
    await _pumpApp(tester, container);

    expect(find.text('Преподаватели'), findsNothing);

    notifier.setState(adminSession());
    await _pumpFrames(tester);

    container.read(goRouterProvider).go('/teachers');
    await _pumpFrames(tester);
    expect(find.text('Преподаватели'), findsWidgets);
  });
}

SessionState studentSessionFor() {
  return SessionState(
    status: SessionStatus.authed,
    token: 't',
    user: auth_api.User(
      id: 'u1',
      email: 'student@example.com',
      isActive: true,
      isSuperuser: false,
      isVerified: true,
      createdAt: DateTime.utc(2026, 1, 1),
      mustChangePassword: false,
    ),
    institution: InstitutionContext(
      id: 'inst-1',
      role: auth_api.UserRole.student,
      name: 'Школа №1',
      currencyName: 'коины',
    ),
  );
}
