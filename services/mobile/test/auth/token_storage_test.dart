import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/auth/token_storage.dart';

void main() {
  group('InMemoryTokenStorage', () {
    test('хранит и возвращает access, refresh и id учреждения', () async {
      final storage = InMemoryTokenStorage();

      expect(await storage.readToken(), isNull);
      expect(await storage.readRefreshToken(), isNull);
      expect(await storage.readLastInstitutionId(), isNull);

      await storage.writeToken('t1');
      await storage.writeRefreshToken('r1');
      await storage.writeLastInstitutionId('inst-1');

      expect(await storage.readToken(), 't1');
      expect(await storage.readRefreshToken(), 'r1');
      expect(await storage.readLastInstitutionId(), 'inst-1');
    });

    test('clear стирает access, refresh и id учреждения (план 10-refresh)', () async {
      final storage = InMemoryTokenStorage();
      await storage.writeToken('t1');
      await storage.writeRefreshToken('r1');
      await storage.writeLastInstitutionId('inst-1');

      await storage.clear();

      expect(await storage.readToken(), isNull);
      expect(await storage.readRefreshToken(), isNull);
      expect(await storage.readLastInstitutionId(), isNull);
    });
  });
}
