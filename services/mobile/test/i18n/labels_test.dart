import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/auth_api.dart';
import 'package:gamification_mobile/api/currency_api.dart';
import 'package:gamification_mobile/api/market_api.dart';
import 'package:gamification_mobile/i18n/labels.dart';

void main() {
  test('роли и статусы членства покрыты подписями полностью', () {
    for (final role in UserRole.values) {
      expect(roleLabels[role], isNotNull, reason: 'нет подписи для $role');
    }
    for (final status in MembershipStatus.values) {
      expect(statusLabels[status], isNotNull, reason: 'нет подписи для $status');
    }
  });

  test('статусы покупки и типы операций покрыты подписями полностью (09b/09c)', () {
    for (final status in PurchaseStatus.values) {
      expect(purchaseStatusLabels[status], isNotNull, reason: 'нет подписи для $status');
    }
    for (final kind in TransactionKind.values) {
      expect(transactionKindLabels[kind], isNotNull, reason: 'нет подписи для $kind');
    }
  });

  test('ученик — русская подпись роли student', () {
    expect(roleLabels[UserRole.student], 'ученик');
  });
}
