/// Riverpod-провайдеры карточки группы (09b) — зеркало
/// `services/web/src/pages/GroupPage.tsx`: ученики группы и все ученики
/// учреждения (для выбора при добавлении, только admin).
///
/// Список групп и список преподавателей — общие с [GroupsScreen] и
/// [TeachersScreen], переиспользуются отсюда же (`groupsProvider`,
/// `teachersProvider`), второй копии не заводится.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/students_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Ученики конкретной группы.
final groupStudentsProvider = FutureProvider.autoDispose.family<List<StudentMember>, String>((ref, groupId) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listStudents(client, institution.id, groupId: groupId);
}, retry: _noRetry);

/// Все ученики учреждения — только для admin, для выбора при добавлении в
/// группу.
final allStudentsProvider = FutureProvider.autoDispose<List<StudentMember>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listStudents(client, institution.id);
}, retry: _noRetry);
