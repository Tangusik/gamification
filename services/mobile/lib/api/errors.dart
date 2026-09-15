/// Разбор ответа API в единую ошибку.
///
/// Контракт сервиса: тело ошибки всегда `{"detail": "MACHINE_READABLE_CODE"}`.
/// Единственное исключение — 422 от валидации FastAPI: там список ошибок по
/// полям, и схлопывать его нельзя, иначе форма потеряет информацию о том,
/// какое именно поле неверно. Правила и коды — зеркало
/// `services/web/src/api/errors.ts`.
library;

/// Ошибки по именам полей формы: `email` → текст от сервера.
typedef FieldErrors = Map<String, String>;

class ApiError implements Exception {
  const ApiError(this.status, this.code, [this.fieldErrors]);

  final int status;

  /// Машинный код из `detail`; для 422 — [validationError].
  final String code;
  final FieldErrors? fieldErrors;

  @override
  String toString() => 'ApiError(status: $status, code: $code)';
}

/// Код, который клиент подставляет, когда запрос не дошёл до сервера
/// (сеть, отмена, таймаут).
const String networkError = 'NETWORK_ERROR';

/// Код 422: подробности лежат в `fieldErrors`.
const String validationError = 'VALIDATION_ERROR';

/// Ответ не разобрался — тело не JSON или не соответствует контракту.
const String unknownError = 'UNKNOWN_ERROR';

/// Требуется контекст учреждения — повод увести на выбор учреждения.
const String institutionContextRequired = 'INSTITUTION_CONTEXT_REQUIRED';

/// Собрать карту «поле → сообщение» из тела 422.
///
/// `loc` выглядит как `["body", "email"]`; именем поля считается последний
/// строковый элемент, потому что вложенных тел у форм этого этапа нет.
FieldErrors? _parseFieldErrors(Object? detail) {
  if (detail is! List) return null;

  final result = <String, String>{};
  for (final raw in detail) {
    if (raw is! Map) continue;
    final loc = raw['loc'];
    final msg = raw['msg'];
    if (loc is List && msg is String) {
      for (final part in loc.reversed) {
        if (part is String) {
          result[part] = msg;
          break;
        }
      }
    }
  }
  return result.isEmpty ? null : result;
}

/// Превратить неуспешный ответ в [ApiError], не бросая на нечитаемом теле.
///
/// Незнакомая форма тела — не повод бросать исключение внутри обработчика
/// ошибок: тогда настоящая ошибка потерялась бы за вторичной.
ApiError toApiError(int status, Object? body) {
  final detail = (body is Map && body.containsKey('detail')) ? body['detail'] : null;

  if (status == 422) {
    return ApiError(422, validationError, _parseFieldErrors(detail));
  }
  if (detail is String && detail.isNotEmpty) {
    return ApiError(status, detail);
  }
  return ApiError(status, unknownError);
}
