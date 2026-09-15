/// Нижние вкладки по ролям — один конфиг «роль → пункты», зеркало
/// `services/web/src/navigation/menu.ts` (раздел 2 плана `09-mobile-app.md`,
/// умолчание, отдельного вопроса не было).
///
/// Экраны за вкладками — заглушки Ч3, их наполняет Ч5. У преподавателя и
/// администратора часть пунктов группируется в «Ещё»: там обычный список
/// ссылок (`MoreLink`), а не отдельные вкладки — так остаётся один и тот же
/// набор веток `StatefulShellRoute` для всех ролей, просто с разным
/// подмножеством видимых вкладок.
library;

import 'package:flutter/material.dart';

import '../api/auth_api.dart' show UserRole;
import 'paths.dart';

/// Ключ ветки `StatefulShellRoute` — фиксированный порядок веток в роутере.
enum TabKey { home, students, market, history, profile, more }

class TabSpec {
  const TabSpec({required this.key, required this.label, required this.icon});

  final TabKey key;
  final String label;
  final IconData icon;
}

const _home = TabSpec(key: TabKey.home, label: 'Главная', icon: Icons.home_outlined);
const _students = TabSpec(key: TabKey.students, label: 'Ученики', icon: Icons.people_outline);
const _market = TabSpec(key: TabKey.market, label: 'Маркет', icon: Icons.storefront_outlined);
const _history = TabSpec(key: TabKey.history, label: 'История', icon: Icons.receipt_long_outlined);
const _profile = TabSpec(key: TabKey.profile, label: 'Профиль', icon: Icons.person_outline);
const _more = TabSpec(key: TabKey.more, label: 'Ещё', icon: Icons.more_horiz);

/// Видимые вкладки для роли, в порядке отображения.
const Map<UserRole, List<TabSpec>> roleTabs = {
  UserRole.student: [_home, _market, _history, _profile],
  UserRole.teacher: [_home, _students, _market, _more],
  UserRole.institutionAdmin: [_home, _students, _market, _more],
};

/// Пункт списка на экране «Ещё»: либо переход на маршрут ([path]), либо
/// переключение на ветку профиля ([switchToProfile]) — профиль живёт в
/// ветке `TabKey.profile`, а не отдельным маршрутом, поэтому у него нет
/// собственного пути.
class MoreLink {
  const MoreLink.route({required this.label, required this.path}) : switchToProfile = false;

  const MoreLink.profile({this.label = 'Профиль'}) : path = null, switchToProfile = true;

  final String label;
  final String? path;
  final bool switchToProfile;
}

/// Пункты экрана «Ещё» по роли — только у преподавателя и администратора.
const Map<UserRole, List<MoreLink>> moreScreenLinks = {
  UserRole.teacher: [
    MoreLink.route(label: 'Группы', path: groupsPath),
    MoreLink.route(label: 'Приглашения', path: invitationsPath),
    MoreLink.profile(),
  ],
  UserRole.institutionAdmin: [
    MoreLink.route(label: 'Преподаватели', path: teachersPath),
    MoreLink.route(label: 'Группы', path: groupsPath),
    MoreLink.route(label: 'Приглашения', path: invitationsPath),
    MoreLink.route(label: 'Настройки учреждения', path: settingsPath),
    MoreLink.profile(),
  ],
};
