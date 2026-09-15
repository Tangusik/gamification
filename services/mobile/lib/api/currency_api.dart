/// Валюта ученика: баланс и история своих операций — зеркало нужной 09a
/// части `services/web/src/api/currency.ts`. Ручное начисление и сторно
/// (роли teacher/admin) — 09b, сюда не переносится.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'auth_api.dart' show UserRole;
import 'client.dart';

/// `purchase` и `purchase_refund` — записи маркета: списание при покупке и
/// возврат при отказе админа.
enum TransactionKind {
  manualAccrual,
  reversal,
  purchase,
  purchaseRefund;

  static TransactionKind fromJson(String value) => switch (value) {
        'manual_accrual' => TransactionKind.manualAccrual,
        'reversal' => TransactionKind.reversal,
        'purchase' => TransactionKind.purchase,
        'purchase_refund' => TransactionKind.purchaseRefund,
        _ => throw ArgumentError('Неизвестный TransactionKind: $value'),
      };
}

class CurrencyTransaction {
  const CurrencyTransaction({
    required this.id,
    required this.kind,
    required this.amount,
    required this.comment,
    required this.createdByName,
    required this.createdByRole,
    required this.createdAt,
    required this.reversesId,
  });

  factory CurrencyTransaction.fromJson(Map<String, dynamic> json) => CurrencyTransaction(
        id: json['id'] as String,
        kind: TransactionKind.fromJson(json['kind'] as String),
        amount: json['amount'] as int,
        comment: json['comment'] as String?,
        createdByName: json['created_by_name'] as String?,
        createdByRole: UserRole.fromJson(json['created_by_role'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        reversesId: json['reverses_id'] as String?,
      );

  final String id;
  final TransactionKind kind;

  /// У сторно (`reversal`) отрицательный.
  final int amount;
  final String? comment;

  /// `null`, если у автора нет имени — тогда показывается роль.
  final String? createdByName;
  final UserRole createdByRole;
  final DateTime createdAt;

  /// У сторно — id начисления, которое оно отменяет; иначе `null`.
  final String? reversesId;
}

class CurrencyAccount {
  const CurrencyAccount({required this.balance, required this.transactions});

  factory CurrencyAccount.fromJson(Map<String, dynamic> json) => CurrencyAccount(
        balance: json['balance'] as int,
        transactions: (json['transactions'] as List<dynamic>)
            .map((item) => CurrencyTransaction.fromJson(item as Map<String, dynamic>))
            .toList(),
      );

  final int balance;

  /// Последние 50 операций, новые сверху.
  final List<CurrencyTransaction> transactions;
}

/// Баланс и история текущего пользователя — доступно только `student`.
Future<CurrencyAccount> getMyCurrency(ApiClient client, String institutionId) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions/${Uri.encodeComponent(institutionId)}/me/currency',
  )
      .then(CurrencyAccount.fromJson);
}
