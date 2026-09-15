import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/errors.dart';

void main() {
  group('toApiError', () {
    test('422 разбирает fieldErrors по последнему строковому loc', () {
      final error = toApiError(422, {
        'detail': [
          {
            'loc': ['body', 'email'],
            'msg': 'value is not a valid email address',
          },
          {
            'loc': ['body', 'password'],
            'msg': 'field required',
          },
        ],
      });

      expect(error.status, 422);
      expect(error.code, validationError);
      expect(error.fieldErrors, {
        'email': 'value is not a valid email address',
        'password': 'field required',
      });
    });

    test('422 без разбираемых элементов даёт fieldErrors == null', () {
      final error = toApiError(422, {'detail': <Object?>[]});

      expect(error.code, validationError);
      expect(error.fieldErrors, isNull);
    });

    test('401 с телом Unauthorized переносит код как есть', () {
      final error = toApiError(401, {'detail': 'Unauthorized'});

      expect(error.status, 401);
      expect(error.code, 'Unauthorized');
      expect(error.fieldErrors, isNull);
    });

    test('строковый detail становится кодом ошибки', () {
      final error = toApiError(409, {'detail': 'OPERATION_ID_CONFLICT'});

      expect(error.status, 409);
      expect(error.code, 'OPERATION_ID_CONFLICT');
    });

    test('нечитаемое тело даёт unknownError, а не исключение', () {
      final error = toApiError(500, 'plain text body');

      expect(error.code, unknownError);
    });

    test('detail отсутствует — unknownError', () {
      final error = toApiError(500, <String, Object?>{});

      expect(error.code, unknownError);
    });
  });
}
