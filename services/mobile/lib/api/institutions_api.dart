/// Онбординг учреждения и приём приглашений — зеркало
/// `services/web/src/api/institutions.ts`, только часть 09a
/// (`GET/POST /institutions`, `POST /institutions/invitations/accept`).
/// Управление учреждением (каталог, настройки, приглашения admin/teacher) —
/// 09b/09c, сюда не переносится.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'auth_api.dart' show InstitutionKind, Membership;
import 'client.dart';

/// Создать учреждение (онбординг). Возвращает id нового учреждения.
Future<String> createInstitution(
  ApiClient client, {
  required String name,
  required InstitutionKind kind,
}) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions',
    method: 'POST',
    json: {'name': name, 'kind': kind.toJson()},
  )
      .then((json) => json['id'] as String);
}

/// Принять приглашение по токену, вставленному пользователем из ссылки
/// (В9 = А плана 09: поле «вставьте ссылку-приглашение», без QR и App Links).
/// Контекст учреждения не нужен — эндпоинт сам находит его по приглашению.
Future<Membership> acceptInvitation(ApiClient client, String invitationToken) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions/invitations/accept',
    method: 'POST',
    json: {'token': invitationToken},
  )
      .then(Membership.fromJson);
}
