/// Валюта: баланс и история одного ученика, ручное начисление и сторно —
/// доступно `teacher` и `institution_admin` (сторно — только
/// `institution_admin`). Зеркало `services/web/src/api/currency.ts`, часть
/// сверх 09a (`currency_api.dart`, не трогается).
///
/// Модели [CurrencyAccount]/[CurrencyTransaction] переиспользуются из
/// `currency_api.dart` — форма ответа одна и та же что для «себя», что для
/// ученика.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'client.dart';
import 'currency_api.dart';

export 'currency_api.dart' show CurrencyAccount, CurrencyTransaction, TransactionKind;

String _institutionPath(String institutionId) => '/institutions/${Uri.encodeComponent(institutionId)}';

/// Баланс и история одного ученика.
Future<CurrencyAccount> listStudentTransactions(ApiClient client, String institutionId, String userId) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/students/${Uri.encodeComponent(userId)}/currency-transactions',
  )
      .then(CurrencyAccount.fromJson);
}

class AccrueInput {
  const AccrueInput({required this.operationId, required this.amount, this.comment});

  final String operationId;
  final int amount;
  final String? comment;

  Map<String, dynamic> toJson() => {
        'operation_id': operationId,
        'amount': amount,
        if (comment != null) 'comment': comment,
      };
}

/// Начислить валюту ученику. Идемпотентно по `operation_id` — см.
/// `newOperationId` в `operation_id.dart`.
Future<CurrencyTransaction> accrue(
  ApiClient client,
  String institutionId,
  String userId,
  AccrueInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/students/${Uri.encodeComponent(userId)}/currency-transactions',
    method: 'POST',
    json: input.toJson(),
  )
      .then(CurrencyTransaction.fromJson);
}

/// Сторнировать начисление — доступно только `institution_admin`.
Future<CurrencyTransaction> reverse(
  ApiClient client,
  String institutionId,
  String transactionId,
  String operationId,
) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/currency-transactions/${Uri.encodeComponent(transactionId)}/reversal',
    method: 'POST',
    json: {'operation_id': operationId},
  )
      .then(CurrencyTransaction.fromJson);
}
