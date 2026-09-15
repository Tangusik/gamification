/// Разбор вставленной ссылки-приглашения — чистая функция, зеркало
/// `location.hash` в `services/web/src/pages/InvitePage.tsx` (В9 = А плана
/// `09-mobile-app.md`: поле «вставьте ссылку-приглашение», без QR и App Links).
///
/// Токен лежит во фрагменте ссылки после `#` и не должен уходить на сервер
/// иначе как в теле запроса. Пользователь может вставить как полную ссылку,
/// так и голый токен — тогда фрагмента нет и в ход идёт вся строка.
library;

/// Достать токен приглашения из вставленного текста; пустая строка, если в
/// тексте ничего нет.
String parseInviteToken(String input) {
  final trimmed = input.trim();
  if (trimmed.isEmpty) return '';
  final hashIndex = trimmed.indexOf('#');
  if (hashIndex == -1) return trimmed;
  return trimmed.substring(hashIndex + 1).trim();
}
