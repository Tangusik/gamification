/// Ученики учреждения — доступно только `institution_admin` (и `teacher` для
/// списка, см. контракт `08-api-contract.md`). Зеркало
/// `services/web/src/api/students.ts`.
///
/// Форма члена ([InstitutionMember]) общая с `teachers_api.dart`.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`. Исключение
/// — [listStudents]: у него необязательный query-параметр `group_id`,
/// который добавляется уже после пути без слэша.
library;

import 'auth_api.dart' show MembershipStatus;
import 'client.dart';
import 'teachers_api.dart' show InstitutionMember, UpdateMemberInput;

export 'teachers_api.dart' show InstitutionMember, UpdateMemberInput;

/// Ученик со своим балансом валюты — поля участника ([InstitutionMember])
/// плюс баланс. Отдельная модель, а не поле в общей форме: у преподавателей
/// (`teachers_api.dart`) баланса нет, и добавлять его в общую форму значило
/// бы соврать про ответ `GET /teachers`.
class StudentMember {
  const StudentMember({
    required this.userId,
    required this.displayName,
    required this.status,
    required this.createdAt,
    required this.groupIds,
    required this.balance,
  });

  factory StudentMember.fromJson(Map<String, dynamic> json) => StudentMember(
        userId: json['user_id'] as String,
        displayName: json['display_name'] as String?,
        status: MembershipStatus.fromJson(json['status'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        groupIds: (json['group_ids'] as List<dynamic>).map((item) => item as String).toList(),
        balance: json['balance'] as int,
      );

  final String userId;
  final String? displayName;
  final MembershipStatus status;
  final DateTime createdAt;
  final List<String> groupIds;
  final int balance;
}

String _studentsPath(String institutionId) =>
    '/institutions/${Uri.encodeComponent(institutionId)}/students';

Future<List<StudentMember>> listStudents(ApiClient client, String institutionId, {String? groupId}) {
  final query = groupId != null ? '?group_id=${Uri.encodeComponent(groupId)}' : '';
  return client
      .request<List<dynamic>>('${_studentsPath(institutionId)}$query')
      .then((list) => list.map((item) => StudentMember.fromJson(item as Map<String, dynamic>)).toList());
}

Future<InstitutionMember> updateStudent(
  ApiClient client,
  String institutionId,
  String userId,
  UpdateMemberInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    '${_studentsPath(institutionId)}/${Uri.encodeComponent(userId)}',
    method: 'PATCH',
    json: input.toJson(),
  )
      .then(InstitutionMember.fromJson);
}
