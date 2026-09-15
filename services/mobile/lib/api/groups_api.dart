/// Группы учреждения — доступно только `institution_admin`. Зеркало
/// `services/web/src/api/groups.ts`.
///
/// Отдельного `GET /groups/{groupId}` в контракте нет: карточка группы
/// находит себя в списке [listGroups].
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'client.dart';

class Group {
  const Group({
    required this.id,
    required this.name,
    required this.teacherIds,
    required this.studentsCount,
  });

  factory Group.fromJson(Map<String, dynamic> json) => Group(
        id: json['id'] as String,
        name: json['name'] as String,
        teacherIds: (json['teacher_ids'] as List<dynamic>).map((item) => item as String).toList(),
        studentsCount: json['students_count'] as int,
      );

  final String id;
  final String name;
  final List<String> teacherIds;
  final int studentsCount;
}

String _groupsPath(String institutionId) =>
    '/institutions/${Uri.encodeComponent(institutionId)}/groups';

String _groupPath(String institutionId, String groupId) =>
    '${_groupsPath(institutionId)}/${Uri.encodeComponent(groupId)}';

Future<List<Group>> listGroups(ApiClient client, String institutionId) {
  return client
      .request<List<dynamic>>(_groupsPath(institutionId))
      .then((list) => list.map((item) => Group.fromJson(item as Map<String, dynamic>)).toList());
}

Future<Group> createGroup(ApiClient client, String institutionId, String name) {
  return client
      .request<Map<String, dynamic>>(_groupsPath(institutionId), method: 'POST', json: {'name': name})
      .then(Group.fromJson);
}

Future<Group> updateGroup(ApiClient client, String institutionId, String groupId, String name) {
  return client
      .request<Map<String, dynamic>>(
    _groupPath(institutionId, groupId),
    method: 'PATCH',
    json: {'name': name},
  )
      .then(Group.fromJson);
}

Future<void> deleteGroup(ApiClient client, String institutionId, String groupId) {
  return client.request<void>(_groupPath(institutionId, groupId), method: 'DELETE');
}

Future<void> addTeacherToGroup(ApiClient client, String institutionId, String groupId, String userId) {
  return client.request<void>(
    '${_groupPath(institutionId, groupId)}/teachers/${Uri.encodeComponent(userId)}',
    method: 'PUT',
  );
}

Future<void> removeTeacherFromGroup(ApiClient client, String institutionId, String groupId, String userId) {
  return client.request<void>(
    '${_groupPath(institutionId, groupId)}/teachers/${Uri.encodeComponent(userId)}',
    method: 'DELETE',
  );
}

Future<void> addStudentToGroup(ApiClient client, String institutionId, String groupId, String userId) {
  return client.request<void>(
    '${_groupPath(institutionId, groupId)}/students/${Uri.encodeComponent(userId)}',
    method: 'PUT',
  );
}

Future<void> removeStudentFromGroup(ApiClient client, String institutionId, String groupId, String userId) {
  return client.request<void>(
    '${_groupPath(institutionId, groupId)}/students/${Uri.encodeComponent(userId)}',
    method: 'DELETE',
  );
}
