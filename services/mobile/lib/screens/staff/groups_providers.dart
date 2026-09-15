/// Riverpod-провайдер списка групп учреждения (09b) — зеркало
/// `services/web/src/pages/GroupsPage.tsx`. Доступен и `institution_admin`, и
/// `teacher` (сервер разрешает обоим `GET /groups`, `require_admin_or_teacher`
/// на бэкенде) — без роли в самом провайдере, это дело экрана.
///
/// `.autoDispose`, без автоповтора — та же причина, что в
/// `lib/screens/student/providers.dart`. Используется и `GroupsScreen`, и
/// `GroupScreen` (карточка группы находит себя в этом же списке — отдельного
/// `GET /groups/{id}` в контракте нет).
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/groups_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final groupsProvider = FutureProvider.autoDispose<List<Group>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listGroups(client, institution.id);
}, retry: _noRetry);
