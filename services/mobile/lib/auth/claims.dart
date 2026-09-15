/// Разбор claims access-токена без проверки подписи — зеркало
/// `services/web/src/auth/claims.ts`.
///
/// Подпись не проверяется и не может: токен уже проверен сервером на каждом
/// запросе, здесь он нужен лишь для мгновенного определения учреждения и
/// срока действия без лишнего запроса. Источник истины по роли и названию —
/// свежий `GET /institutions` в сессии, сам claim может отставать от него до
/// 900 секунд (время жизни токена).
library;

import 'dart:convert';

/// Достать `institution_id` из access-токена; `null`, если его нет или токен
/// не разобрать.
String? decodeInstitutionId(String token) {
  final value = _decodePayload(token)?['institution_id'];
  return value is String ? value : null;
}

/// Момент истечения токена (claim `exp`, секунды Unix) в UTC; `null`, если
/// claim отсутствует или токен не разобрать — такой токен считается
/// непригодным (см. [isExpired]).
DateTime? decodeExpiry(String token) {
  final value = _decodePayload(token)?['exp'];
  if (value is int) {
    return DateTime.fromMillisecondsSinceEpoch(value * 1000, isUtc: true);
  }
  if (value is num) {
    return DateTime.fromMillisecondsSinceEpoch((value * 1000).round(), isUtc: true);
  }
  return null;
}

/// Истёк ли токен на момент [now] (по умолчанию — текущее время). Токен без
/// claim `exp` или который не удалось разобрать считается истёкшим: на
/// сервере `exp` обязателен (`06-identity-and-tokens.md`), поэтому его
/// отсутствие — признак повреждённого значения, а не легитимного токена.
bool isExpired(String token, {DateTime? now}) {
  final expiry = decodeExpiry(token);
  if (expiry == null) return true;
  return !expiry.isAfter((now ?? DateTime.now()).toUtc());
}

Map<String, dynamic>? _decodePayload(String token) {
  final parts = token.split('.');
  if (parts.length < 2) return null;
  try {
    var normalized = parts[1].replaceAll('-', '+').replaceAll('_', '/');
    normalized += '=' * ((4 - normalized.length % 4) % 4);
    final json = utf8.decode(base64.decode(normalized));
    final parsed = jsonDecode(json);
    return parsed is Map<String, dynamic> ? parsed : null;
  } catch (_) {
    return null;
  }
}
