/// Управление учреждением: настройки и приглашения — доступно только
/// `institution_admin`. Зеркало `services/web/src/api/institutions.ts`
/// (без `createInstitution`/`acceptInvitation` — те уже есть в
/// `institutions_api.dart`, не дублируются здесь).
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'auth_api.dart' show InstitutionKind, UserRole;
import 'client.dart';

class Institution {
  const Institution({
    required this.id,
    required this.name,
    required this.kind,
    required this.createdAt,
    required this.currencyName,
  });

  factory Institution.fromJson(Map<String, dynamic> json) => Institution(
        id: json['id'] as String,
        name: json['name'] as String,
        kind: InstitutionKind.fromJson(json['kind'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        currencyName: json['currency_name'] as String?,
      );

  final String id;
  final String name;
  final InstitutionKind kind;
  final DateTime createdAt;

  /// Название внутренней валюты (В5/б); `null`, пока не задано.
  final String? currencyName;
}

Future<Institution> getInstitution(ApiClient client, String institutionId) {
  return client
      .request<Map<String, dynamic>>('/institutions/${Uri.encodeComponent(institutionId)}')
      .then(Institution.fromJson);
}

/// Сентинел для [UpdateInstitutionInput.currencyName]: отличает «поле не
/// передано» от «передано и явно равно `null`» (очистка названия валюты —
/// запасное слово тогда снова берёт форматирование по умолчанию).
const Object unsetCurrencyName = Object();

/// Только изменяемые поля учреждения (В5/б, `InstitutionSettingsScreen`).
/// Непереданные поля не должны попадать в тело запроса вовсе.
class UpdateInstitutionInput {
  const UpdateInstitutionInput({this.name, this.currencyName = unsetCurrencyName});

  final String? name;

  /// `String?` или [unsetCurrencyName] (по умолчанию — не передавать).
  final Object? currencyName;

  Map<String, dynamic> toJson() => {
        if (name != null) 'name': name,
        if (!identical(currencyName, unsetCurrencyName)) 'currency_name': currencyName,
      };
}

/// Обновить настройки учреждения — доступно только `institution_admin`.
Future<Institution> updateInstitution(
  ApiClient client,
  String institutionId,
  UpdateInstitutionInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions/${Uri.encodeComponent(institutionId)}',
    method: 'PATCH',
    json: input.toJson(),
  )
      .then(Institution.fromJson);
}

class InvitationRead {
  const InvitationRead({
    required this.id,
    required this.token,
    required this.role,
    required this.maxUses,
    required this.usesCount,
    required this.createdBy,
    required this.createdAt,
    required this.revokedAt,
  });

  factory InvitationRead.fromJson(Map<String, dynamic> json) => InvitationRead(
        id: json['id'] as String,
        token: json['token'] as String,
        role: UserRole.fromJson(json['role'] as String),
        maxUses: json['max_uses'] as int,
        usesCount: json['uses_count'] as int,
        createdBy: json['created_by'] as String,
        createdAt: DateTime.parse(json['created_at'] as String),
        revokedAt: json['revoked_at'] == null ? null : DateTime.parse(json['revoked_at'] as String),
      );

  final String id;
  final String token;
  final UserRole role;
  final int maxUses;
  final int usesCount;
  final String createdBy;
  final DateTime createdAt;
  final DateTime? revokedAt;
}

String _invitationsPath(String institutionId) =>
    '/institutions/${Uri.encodeComponent(institutionId)}/invitations';

Future<InvitationRead> createInvitation(ApiClient client, String institutionId, int maxUses) {
  return client
      .request<Map<String, dynamic>>(
    _invitationsPath(institutionId),
    method: 'POST',
    json: {'max_uses': maxUses},
  )
      .then(InvitationRead.fromJson);
}

Future<List<InvitationRead>> listInvitations(ApiClient client, String institutionId) {
  return client
      .request<List<dynamic>>(_invitationsPath(institutionId))
      .then((list) => list.map((item) => InvitationRead.fromJson(item as Map<String, dynamic>)).toList());
}

Future<void> revokeInvitation(ApiClient client, String institutionId, String invitationId) {
  return client.request<void>(
    '${_invitationsPath(institutionId)}/${Uri.encodeComponent(invitationId)}',
    method: 'DELETE',
  );
}
