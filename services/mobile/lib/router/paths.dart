/// Пути маршрутов 09b/09c — экраны импортируют их отсюда, а не из
/// `app_router.dart`, чтобы не заводить циклов (экраны → пути, роутер →
/// экраны и пути).
///
/// Существующие пути 09a остались объявлены здесь же и реэкспортированы из
/// `app_router.dart`, чтобы публичные имена не менялись.
library;

const String loginPath = '/login';
const String registerPath = '/register';
const String passwordPath = '/password';
const String institutionsPath = '/institutions';
const String invitePath = '/invite';
const String demoPath = '/demo';
const String splashPath = '/splash';

/// Ветка «Ученики» — список и карточка ученика (teacher, admin).
const String studentsPath = '/students';
String studentCardPath(String userId) => '/students/${Uri.encodeComponent(userId)}';

/// Ветка «Маркет»: student видит корень как каталог с покупкой, teacher — как
/// каталог только на чтение, admin — как раздел с вложенными «Каталог» и
/// «Заявки».
const String marketPath = '/market';
const String marketPrivilegesPath = '/market/privileges';
const String marketPurchasesPath = '/market/purchases';

/// Верхнего уровня — открываются через `context.push`, как сейчас из «Ещё»
/// (teacher, admin — по составу `tabs.dart`).
const String groupsPath = '/groups';
String groupPath(String groupId) => '/groups/${Uri.encodeComponent(groupId)}';
const String invitationsPath = '/invitations';
const String teachersPath = '/teachers';
const String settingsPath = '/settings';
