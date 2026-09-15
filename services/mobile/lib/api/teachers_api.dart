/// Преподаватели учреждения — доступно только `institution_admin`. Зеркало
/// `services/web/src/api/teachers.ts`.
///
/// [InstitutionMember] общий с `students_api.dart`: сервер отдаёт его в
/// одном виде для обеих ролей — модель лежит здесь, `students_api.dart` её
/// импортирует.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'auth_api.dart' show MembershipStatus;
import 'client.dart';

/// Член учреждения в списках преподавателей/учеников.
class InstitutionMember {
  const InstitutionMember({
    required this.userId,
    required this.displayName,
    required this.status,
    required this.createdAt,
    required this.groupIds,
  });

  factory InstitutionMember.fromJson(Map<String, dynamic> json) => InstitutionMember(
        userId: json['user_id'] as String,
        displayName: json['display_name'] as String?,
        status: MembershipStatus.fromJson(json['status'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        groupIds: (json['group_ids'] as List<dynamic>).map((item) => item as String).toList(),
      );

  final String userId;
  final String? displayName;
  final MembershipStatus status;
  final DateTime createdAt;
  final List<String> groupIds;
}

class CreateTeacherInput {
  const CreateTeacherInput({required this.email, required this.password, required this.displayName});

  final String email;
  final String password;
  final String displayName;

  Map<String, dynamic> toJson() => {
        'email': email,
        'password': password,
        'display_name': displayName,
      };
}

/// Любые поля необязательны — непереданные не должны попадать в тело запроса
/// вовсе (см. `UpdateMemberInput` веба).
class UpdateMemberInput {
  const UpdateMemberInput({this.displayName, this.status});

  final String? displayName;
  final MembershipStatus? status;

  Map<String, dynamic> toJson() => {
        if (displayName != null) 'display_name': displayName,
        if (status != null) 'status': status!.toJson(),
      };
}

String _teachersPath(String institutionId) =>
    '/institutions/${Uri.encodeComponent(institutionId)}/teachers';

Future<InstitutionMember> createTeacher(
  ApiClient client,
  String institutionId,
  CreateTeacherInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    _teachersPath(institutionId),
    method: 'POST',
    json: input.toJson(),
  )
      .then(InstitutionMember.fromJson);
}

Future<List<InstitutionMember>> listTeachers(ApiClient client, String institutionId) {
  return client
      .request<List<dynamic>>(_teachersPath(institutionId))
      .then((list) => list.map((item) => InstitutionMember.fromJson(item as Map<String, dynamic>)).toList());
}

Future<InstitutionMember> updateTeacher(
  ApiClient client,
  String institutionId,
  String userId,
  UpdateMemberInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    '${_teachersPath(institutionId)}/${Uri.encodeComponent(userId)}',
    method: 'PATCH',
    json: input.toJson(),
  )
      .then(InstitutionMember.fromJson);
}
