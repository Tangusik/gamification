import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/claims.dart';

import 'test_support.dart';

void main() {
  group('decodeInstitutionId', () {
    test('достаёт institution_id из payload', () {
      final token = fakeJwt({'sub': 'u1', 'institution_id': 'inst-1'});
      expect(decodeInstitutionId(token), 'inst-1');
    });

    test('null, если claim отсутствует', () {
      final token = fakeJwt({'sub': 'u1'});
      expect(decodeInstitutionId(token), isNull);
    });

    test('null для мусорной строки', () {
      expect(decodeInstitutionId('не.токен'), isNull);
    });
  });

  group('isExpired', () {
    test('живой токен не истёк', () {
      final token = fakeJwt({'exp': unixSecondsFromNow(const Duration(minutes: 15))});
      expect(isExpired(token), isFalse);
    });

    test('токен с прошедшим exp истёк', () {
      final token = fakeJwt({'exp': unixSecondsFromNow(const Duration(minutes: -1))});
      expect(isExpired(token), isTrue);
    });

    test('токен без exp считается истёкшим', () {
      final token = fakeJwt({'sub': 'u1'});
      expect(isExpired(token), isTrue);
    });

    test('нечитаемый токен считается истёкшим', () {
      expect(isExpired('битый-токен'), isTrue);
    });
  });
}
