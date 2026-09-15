/// Карта маршрутов — зеркало `services/web/src/router.tsx`, только на
/// `go_router` (решение В7 плана `09-mobile-app.md`).
///
/// `redirect` покрывает то, что в вебе делают `RequireAuth`/`RequireAnon`,
/// `must_change_password` (`RequireAuth`, `fromLocation.ts`) и отсутствие
/// контекста учреждения. Нижние вкладки — `StatefulShellRoute`, состав по
/// роли — `tabs.dart`. Экраны 09b/09c — заглушки Ч3 этапа
/// `.claude/plans/09b-09c-mobile-staff.md`, наполняет их шаг 2.
///
/// **Проверка роли — в билдере маршрута**, не только в составе вкладок
/// (`tabs.dart`): меню (вкладки и «Ещё») только прячет пункты, прямой переход
/// по пути чужой роли должен получать [ScreenStateForbidden], а не экран
/// чужой роли — тот же принцип, что в `menu.ts` веба («меню только скрывает
/// недоступное, защита остаётся на бэкенде»); здесь защиты бэкенда мало,
/// потому что экран мог успеть смонтироваться до ответа сервера.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../api/auth_api.dart' show UserRole;
import '../auth/session.dart';
import '../screens/admin/admin_market_screen.dart';
import '../screens/admin/institution_settings_screen.dart';
import '../screens/admin/pending_count.dart';
import '../screens/admin/privileges_screen.dart';
import '../screens/admin/purchases_screen.dart';
import '../screens/admin/teachers_screen.dart';
import '../screens/common/change_password_screen.dart';
import '../screens/common/institutions_screen.dart';
import '../screens/common/invite_screen.dart';
import '../screens/common/login_screen.dart';
import '../screens/common/profile_screen.dart';
import '../screens/common/register_screen.dart';
import '../screens/staff/group_screen.dart';
import '../screens/staff/groups_screen.dart';
import '../screens/staff/invitations_screen.dart';
import '../screens/staff/staff_home_screen.dart';
import '../screens/staff/student_card_screen.dart';
import '../screens/staff/students_screen.dart';
import '../screens/staff/teacher_market_screen.dart';
import '../screens/student/history_screen.dart';
import '../screens/student/market_screen.dart';
import '../screens/student/student_home_screen.dart';
import '../ui/demo_screen.dart';
import '../ui/screen_state.dart';
import 'placeholder_screens.dart';
import 'paths.dart';
import 'tabs.dart';

export 'paths.dart';

/// Пути, доступные без выбранного учреждения — как `/institutions` в вебе
/// (сам этот экран контекста не требует).
const Set<String> _institutionExemptPaths = {
  loginPath,
  registerPath,
  passwordPath,
  institutionsPath,
  invitePath,
  demoPath,
  splashPath,
};

/// Фиксированный порядок веток `StatefulShellRoute` — общий для всех ролей,
/// видимое подмножество задаёт `roleTabs`.
final Map<TabKey, String> _branchPaths = {
  TabKey.home: '/',
  TabKey.students: studentsPath,
  TabKey.market: marketPath,
  TabKey.history: '/history',
  TabKey.profile: '/profile',
  TabKey.more: '/more',
};

/// Обёртка, транслирующая изменения [sessionProvider] в `GoRouter.refresh()`
/// — идиоматичный мост Riverpod ↔ go_router, без пересборки роутера целиком.
class _RouterRefreshNotifier extends ChangeNotifier {
  _RouterRefreshNotifier(Ref ref) {
    ref.listen(sessionProvider, (_, _) => notifyListeners());
  }
}

final goRouterProvider = Provider<GoRouter>((ref) {
  final refresh = _RouterRefreshNotifier(ref);
  return GoRouter(
    initialLocation: splashPath,
    refreshListenable: refresh,
    redirect: (context, state) => _redirect(ref, state),
    routes: [
      GoRoute(path: splashPath, builder: (context, state) => const AuthPendingScreen()),
      GoRoute(path: loginPath, builder: (context, state) => const LoginScreen()),
      GoRoute(path: registerPath, builder: (context, state) => const RegisterScreen()),
      GoRoute(path: passwordPath, builder: (context, state) => const ChangePasswordScreen()),
      GoRoute(path: institutionsPath, builder: (context, state) => const InstitutionsScreen()),
      // Токен приглашения в маршрут не попадает (находка С1 ревью
      // безопасности, `09-mobile-app.md`, Ч6) — ссылку, вставленную анонимом,
      // экран сам передаёт через `pendingInviteProvider`.
      GoRoute(path: invitePath, builder: (context, state) => const InviteScreen()),
      GoRoute(path: demoPath, builder: (context, state) => const DemoScreen()),
      // Пункты экрана «Ещё» преподавателя и администратора — верхнего
      // уровня, открываются через `context.push`.
      GoRoute(
        path: groupsPath,
        builder: (context, state) => _roleGate(const {UserRole.teacher, UserRole.institutionAdmin}, const GroupsScreen()),
      ),
      GoRoute(
        path: '$groupsPath/:groupId',
        builder: (context, state) => _roleGate(
          const {UserRole.teacher, UserRole.institutionAdmin},
          GroupScreen(groupId: state.pathParameters['groupId']!),
        ),
      ),
      GoRoute(
        path: invitationsPath,
        builder: (context, state) =>
            _roleGate(const {UserRole.teacher, UserRole.institutionAdmin}, const InvitationsScreen()),
      ),
      GoRoute(
        path: teachersPath,
        builder: (context, state) => _roleGate(const {UserRole.institutionAdmin}, const TeachersScreen()),
      ),
      GoRoute(
        path: settingsPath,
        builder: (context, state) =>
            _roleGate(const {UserRole.institutionAdmin}, const InstitutionSettingsScreen()),
      ),
      _buildShell(ref),
    ],
  );
});

/// Обёртка маршрута общей проверкой роли (см. пояснение в шапке файла):
/// [allowed] — роли, которым путь доступен; иначе — [ScreenStateForbidden].
/// `role == null` (мембершипы ещё грузятся) — [AuthPendingScreen], как и
/// у веток `StatefulShellRoute`.
Widget _roleGate(Set<UserRole> allowed, Widget screen) {
  return Consumer(
    builder: (context, ref, _) {
      final role = ref.watch(sessionProvider.select((state) => state.institution?.role));
      if (role == null) return const AuthPendingScreen();
      if (!allowed.contains(role)) return const _ForbiddenScreen();
      return screen;
    },
  );
}

class _ForbiddenScreen extends StatelessWidget {
  const _ForbiddenScreen();

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Нет доступа')),
      body: const Padding(padding: EdgeInsets.all(24), child: ScreenStateForbidden()),
    );
  }
}

StatefulShellRoute _buildShell(Ref ref) {
  return StatefulShellRoute.indexedStack(
    builder: (context, state, navigationShell) => _AppShell(navigationShell: navigationShell),
    branches: [
      _branch(TabKey.home, (context, state, role) {
        if (role == null) return const AuthPendingScreen();
        return role == UserRole.student ? const StudentHomeScreen() : const StaffHomeScreen();
      }),
      StatefulShellBranch(
        routes: [
          GoRoute(
            path: studentsPath,
            builder: (context, state) =>
                _roleGate(const {UserRole.teacher, UserRole.institutionAdmin}, const StudentsScreen()),
            routes: [
              GoRoute(
                path: ':userId',
                builder: (context, state) => _roleGate(
                  const {UserRole.teacher, UserRole.institutionAdmin},
                  StudentCardScreen(userId: state.pathParameters['userId']!),
                ),
              ),
            ],
          ),
        ],
      ),
      StatefulShellBranch(
        routes: [
          GoRoute(
            path: marketPath,
            builder: (context, state) => Consumer(
              builder: (context, ref, _) {
                final role = ref.watch(sessionProvider.select((state) => state.institution?.role));
                return switch (role) {
                  null => const AuthPendingScreen(),
                  UserRole.student => const MarketScreen(),
                  UserRole.teacher => const TeacherMarketScreen(),
                  UserRole.institutionAdmin => const AdminMarketScreen(),
                };
              },
            ),
            routes: [
              GoRoute(
                path: 'privileges',
                builder: (context, state) =>
                    _roleGate(const {UserRole.institutionAdmin}, const PrivilegesScreen()),
              ),
              GoRoute(
                path: 'purchases',
                builder: (context, state) =>
                    _roleGate(const {UserRole.institutionAdmin}, const PurchasesScreen()),
              ),
            ],
          ),
        ],
      ),
      _branch(TabKey.history, (context, state, role) {
        if (role == null) return const AuthPendingScreen();
        return role == UserRole.student ? const HistoryScreen() : const _ForbiddenScreen();
      }),
      _branch(TabKey.profile, (context, state, role) => const ProfileScreen()),
      _branch(TabKey.more, (context, state, role) => const _MoreScreen()),
    ],
  );
}

/// Ветка с одним листовым маршрутом; роль читается провайдером сессии внутри
/// билдера, а не пробрасывается параметром.
StatefulShellBranch _branch(
  TabKey key,
  Widget Function(BuildContext, GoRouterState, UserRole?) builder,
) {
  return StatefulShellBranch(
    routes: [
      GoRoute(
        path: _branchPaths[key]!,
        builder: (context, state) => Consumer(
          builder: (context, ref, _) => builder(context, state, ref.watch(sessionProvider).institution?.role),
        ),
      ),
    ],
  );
}

class _AppShell extends ConsumerStatefulWidget {
  const _AppShell({required this.navigationShell});

  final StatefulNavigationShell navigationShell;

  @override
  ConsumerState<_AppShell> createState() => _AppShellState();
}

/// `WidgetsBindingObserver` — аналог `visibilitychange`/`focus` веба
/// (`usePendingPurchasesCount.ts`): при возврате приложения на передний план
/// счётчик заявок перечитывается заново.
class _AppShellState extends ConsumerState<_AppShell> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      ref.invalidate(pendingPurchasesCountProvider);
    }
  }

  @override
  Widget build(BuildContext context) {
    final role = ref.watch(sessionProvider).institution?.role;
    final tabs = role == null ? const <TabSpec>[] : (roleTabs[role] ?? const <TabSpec>[]);
    final branchIndexes = tabs.map((tab) => TabKey.values.indexOf(tab.key)).toList();
    final pendingCount = ref.watch(pendingPurchasesCountProvider).when(
      data: (value) => value,
      error: (_, _) => null,
      loading: () => null,
    );

    if (tabs.isEmpty) {
      // Роль ещё не известна (мембершипы загружаются) — без нижней панели.
      return widget.navigationShell;
    }

    final currentTabIndex = branchIndexes.indexOf(widget.navigationShell.currentIndex);

    return Scaffold(
      body: widget.navigationShell,
      bottomNavigationBar: NavigationBar(
        selectedIndex: currentTabIndex < 0 ? 0 : currentTabIndex,
        onDestinationSelected: (index) {
          // Аналог смены маршрута в вебе (`usePendingPurchasesCount.ts`) —
          // счётчик заявок перечитывается при каждом переключении вкладки.
          ref.invalidate(pendingPurchasesCountProvider);
          widget.navigationShell.goBranch(
            branchIndexes[index],
            initialLocation: branchIndexes[index] == widget.navigationShell.currentIndex,
          );
        },
        destinations: [
          for (final tab in tabs)
            NavigationDestination(
              icon: tab.key == TabKey.market && pendingCount != null && pendingCount > 0
                  ? Badge(label: Text('$pendingCount'), child: Icon(tab.icon))
                  : Icon(tab.icon),
              label: tab.label,
            ),
        ],
      ),
    );
  }
}

/// Экран «Ещё» — список ссылок для преподавателя и администратора
/// (`tabs.dart`). «Профиль» переключает ветку профиля вместо перехода по пути.
class _MoreScreen extends ConsumerWidget {
  const _MoreScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final role = ref.watch(sessionProvider).institution?.role;
    final links = role == null ? const <MoreLink>[] : (moreScreenLinks[role] ?? const <MoreLink>[]);
    return Scaffold(
      appBar: AppBar(title: const Text('Ещё')),
      body: ListView(
        children: [
          for (final link in links)
            ListTile(
              title: Text(link.label),
              onTap: () {
                if (link.switchToProfile) {
                  final shell = StatefulNavigationShell.maybeOf(context);
                  shell?.goBranch(TabKey.values.indexOf(TabKey.profile));
                } else {
                  context.push(link.path!);
                }
              },
            ),
        ],
      ),
    );
  }
}

String? _redirect(Ref ref, GoRouterState state) {
  final session = ref.read(sessionProvider);
  final path = state.matchedLocation;

  // Демо-экран доступен всегда, вне зависимости от статуса сессии.
  if (path == demoPath) return null;

  if (session.status == SessionStatus.loading) {
    return path == splashPath ? null : splashPath;
  }
  if (path == splashPath) {
    // Статус уже известен — уходим со сплеша, дальше решают правила ниже
    // (go_router автоматически повторяет redirect для новой цели).
    return '/';
  }

  final isAnonRoute = path == loginPath || path == registerPath;

  if (session.status == SessionStatus.anon) {
    if (isAnonRoute || path == invitePath) return null;
    return Uri(path: loginPath, queryParameters: {'from': path}).toString();
  }

  // status == authed:
  if (isAnonRoute) {
    final from = state.uri.queryParameters['from'];
    return (from != null && from.isNotEmpty) ? from : '/';
  }

  if (session.user?.mustChangePassword == true && path != passwordPath) {
    return passwordPath;
  }

  // Экран выбора учреждения — только «зал ожидания»: как только контекст
  // разрешился сам (автовыбор), незачем на нём задерживаться, пользователь
  // туда явно не переходил.
  if (path == institutionsPath && session.institution != null && !session.needsInstitutionSelection) {
    return '/';
  }

  final requiresInstitution = !_institutionExemptPaths.contains(path);
  if (requiresInstitution && (session.institution == null || session.needsInstitutionSelection)) {
    return institutionsPath;
  }

  return null;
}
