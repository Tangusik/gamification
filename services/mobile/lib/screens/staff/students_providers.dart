/// Riverpod-провайдеры данных для раздела «Ученики» (09b) — список учеников
/// (используется и списком, и карточкой одного ученика — источник тот же,
/// что в вебе, отдельного ресурса «один ученик» в контракте нет) и список
/// групп учреждения для подписей и фильтра.
///
/// Без кодогенерации, по образцу `lib/screens/student/providers.dart`:
/// `.autoDispose`, учреждение — из [sessionProvider], автоповтор Riverpod
/// отключён (`retry: _noRetry`) — у экранов есть кнопка «Повторить».
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/groups_api.dart';
import '../../api/students_api.dart';
import '../../auth/session.dart';

Duration? _noRetry(int retryCount, Object error) => null;

/// Ученики учреждения — `institution_admin` видит всех, `teacher` — только
/// своих групп (фильтрует сервер, см. `students_api.dart`).
final studentsListProvider = FutureProvider.autoDispose<List<StudentMember>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listStudents(client, institution.id);
}, retry: _noRetry);

/// Группы учреждения — для подписи группы ученика и фильтра в списке.
final staffGroupsProvider = FutureProvider.autoDispose<List<Group>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listGroups(client, institution.id);
}, retry: _noRetry);

/// Найти ученика по id в уже загруженном списке — как `students.find(...)`
/// веба: отдельного `GET` на одного ученика в контракте нет.
StudentMember? findStudent(List<StudentMember> students, String userId) {
  for (final student in students) {
    if (student.userId == userId) return student;
  }
  return null;
}

/// Имя группы по id или `—`, если группа ещё не загружена/неизвестна.
String groupNameOrDash(List<Group>? groups, String groupId) {
  if (groups == null) return '—';
  for (final group in groups) {
    if (group.id == groupId) return group.name;
  }
  return '—';
}
