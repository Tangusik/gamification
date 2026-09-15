/// Маркет привилегий, часть администратора (09c) — каталог (создание,
/// изменение) и очередь решений по заявкам. Зеркало
/// `services/web/src/api/market.ts`, сверх среза 09a (`market_api.dart`, не
/// трогается — модели [Privilege]/[Purchase]/[PurchaseStatus] переиспользуются
/// оттуда).
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'client.dart';
import 'market_api.dart';

export 'market_api.dart' show Privilege, Purchase, PurchaseStatus;

class CreatePrivilegeInput {
  const CreatePrivilegeInput({
    required this.title,
    this.description,
    required this.price,
    this.stock,
    this.isActive,
  });

  final String title;
  final String? description;
  final int price;

  /// `null` — без ограничения (L2).
  final int? stock;
  final bool? isActive;

  Map<String, dynamic> toJson() => {
        'title': title,
        if (description != null) 'description': description,
        'price': price,
        if (stock != null) 'stock': stock,
        if (isActive != null) 'is_active': isActive,
      };
}

/// Сентинел для полей [UpdatePrivilegeInput], которым нужно уметь явно
/// сбросить значение в `null` (например, `stock` — «без ограничения»).
/// Непереданные поля не должны попадать в тело запроса вовсе — сервер
/// различает «поле не передано» и `null` через `model_fields_set` (У11).
const Object unsetField = Object();

class UpdatePrivilegeInput {
  const UpdatePrivilegeInput({
    this.title,
    this.description = unsetField,
    this.price,
    this.stock = unsetField,
    this.isActive,
  });

  final String? title;

  /// `String?` или [unsetField] (по умолчанию — не передавать).
  final Object? description;
  final int? price;

  /// `int?` или [unsetField] (по умолчанию — не передавать).
  final Object? stock;
  final bool? isActive;

  Map<String, dynamic> toJson() => {
        if (title != null) 'title': title,
        if (!identical(description, unsetField)) 'description': description,
        if (price != null) 'price': price,
        if (!identical(stock, unsetField)) 'stock': stock,
        if (isActive != null) 'is_active': isActive,
      };
}

/// Фильтр `GET .../purchases` — доступно только `institution_admin`.
/// `status: pending` отдаётся без лимита (У8), остальные фильтры — последние
/// 50.
class ListPurchasesFilter {
  const ListPurchasesFilter({this.status, this.userId});

  final PurchaseStatus? status;
  final String? userId;
}

String _institutionPath(String institutionId) => '/institutions/${Uri.encodeComponent(institutionId)}';

String _purchaseStatusJson(PurchaseStatus status) => switch (status) {
      PurchaseStatus.pending => 'pending',
      PurchaseStatus.fulfilled => 'fulfilled',
      PurchaseStatus.rejected => 'rejected',
    };

/// Создать позицию каталога — доступно только `institution_admin`.
Future<Privilege> createPrivilege(ApiClient client, String institutionId, CreatePrivilegeInput input) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/privileges',
    method: 'POST',
    json: input.toJson(),
  )
      .then(Privilege.fromJson);
}

/// Изменить позицию каталога — доступно только `institution_admin`.
Future<Privilege> updatePrivilege(
  ApiClient client,
  String institutionId,
  String privilegeId,
  UpdatePrivilegeInput input,
) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/privileges/${Uri.encodeComponent(privilegeId)}',
    method: 'PATCH',
    json: input.toJson(),
  )
      .then(Privilege.fromJson);
}

/// Покупки учреждения — доступно только `institution_admin`.
Future<List<Purchase>> listPurchases(
  ApiClient client,
  String institutionId, {
  ListPurchasesFilter filter = const ListPurchasesFilter(),
}) {
  final params = <String, String>{};
  if (filter.status != null) params['status'] = _purchaseStatusJson(filter.status!);
  if (filter.userId != null) params['user_id'] = filter.userId!;
  final query = params.isEmpty
      ? ''
      : '?${params.entries.map((e) => '${e.key}=${Uri.encodeComponent(e.value)}').join('&')}';
  return client
      .request<List<dynamic>>('${_institutionPath(institutionId)}/purchases$query')
      .then((list) => list.map((item) => Purchase.fromJson(item as Map<String, dynamic>)).toList());
}

/// Отметить покупку выданной — доступно только `institution_admin`,
/// идемпотентно по статусу.
Future<Purchase> fulfilPurchase(ApiClient client, String institutionId, String purchaseId) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/purchases/${Uri.encodeComponent(purchaseId)}/fulfil',
    method: 'POST',
  )
      .then(Purchase.fromJson);
}

/// Отклонить покупку — доступно только `institution_admin`, возвращает
/// валюту и остаток.
Future<Purchase> rejectPurchase(ApiClient client, String institutionId, String purchaseId) {
  return client
      .request<Map<String, dynamic>>(
    '${_institutionPath(institutionId)}/purchases/${Uri.encodeComponent(purchaseId)}/reject',
    method: 'POST',
  )
      .then(Purchase.fromJson);
}
