/// Маркет привилегий, часть ученика (09a) — зеркало нужного среза
/// `services/web/src/api/market.ts`. Каталог и решения по заявкам
/// (роль admin) — 09c, сюда не переносится.
///
/// Пути даны без завершающего слэша — см. правило в `client.dart`.
library;

import 'client.dart';

class Privilege {
  const Privilege({
    required this.id,
    required this.title,
    required this.description,
    required this.price,
    required this.stock,
    required this.isActive,
  });

  factory Privilege.fromJson(Map<String, dynamic> json) => Privilege(
        id: json['id'] as String,
        title: json['title'] as String,
        description: json['description'] as String?,
        price: json['price'] as int,
        stock: json['stock'] as int?,
        isActive: json['is_active'] as bool,
      );

  final String id;
  final String title;
  final String? description;
  final int price;

  /// `null` — без ограничения.
  final int? stock;
  final bool isActive;
}

enum PurchaseStatus {
  pending,
  fulfilled,
  rejected;

  static PurchaseStatus fromJson(String value) => switch (value) {
        'pending' => PurchaseStatus.pending,
        'fulfilled' => PurchaseStatus.fulfilled,
        'rejected' => PurchaseStatus.rejected,
        _ => throw ArgumentError('Неизвестный PurchaseStatus: $value'),
      };
}

class Purchase {
  const Purchase({
    required this.id,
    required this.privilegeId,
    required this.title,
    required this.price,
    required this.status,
    required this.createdAt,
    required this.resolvedAt,
    this.userId,
    this.userName,
  });

  factory Purchase.fromJson(Map<String, dynamic> json) => Purchase(
        id: json['id'] as String,
        privilegeId: json['privilege_id'] as String,
        title: json['title'] as String,
        price: json['price'] as int,
        status: PurchaseStatus.fromJson(json['status'] as String),
        createdAt: DateTime.parse(json['created_at'] as String),
        resolvedAt:
            json['resolved_at'] == null ? null : DateTime.parse(json['resolved_at'] as String),
        userId: json['user_id'] as String?,
        userName: json['user_name'] as String?,
      );

  final String id;
  final String privilegeId;

  /// Снимок на момент покупки — не текущее название позиции каталога.
  final String title;
  final int price;
  final PurchaseStatus status;
  final DateTime createdAt;
  final DateTime? resolvedAt;

  /// Заполнены только в админском списке (`GET .../purchases`) — ответ
  /// `GET .../me/purchases` их не отдаёт.
  final String? userId;
  final String? userName;
}

/// Каталог привилегий: ученик видит только активные позиции.
Future<List<Privilege>> listPrivileges(ApiClient client, String institutionId) {
  return client
      .request<List<dynamic>>('/institutions/${Uri.encodeComponent(institutionId)}/privileges')
      .then((list) => list.map((item) => Privilege.fromJson(item as Map<String, dynamic>)).toList());
}

/// Купить привилегию. Идемпотентно по `operationId`
/// (см. `newOperationId` в `operation_id.dart`): повтор того же тела
/// возвращает уже созданную покупку (сервер отвечает 200 вместо 201), для
/// вызывающего кода разница не важна.
Future<Purchase> purchase(
  ApiClient client,
  String institutionId, {
  required String operationId,
  required String privilegeId,
  required int expectedPrice,
}) {
  return client
      .request<Map<String, dynamic>>(
    '/institutions/${Uri.encodeComponent(institutionId)}/purchases',
    method: 'POST',
    json: {
      'operation_id': operationId,
      'privilege_id': privilegeId,
      'expected_price': expectedPrice,
    },
  )
      .then(Purchase.fromJson);
}

/// Свои покупки — последние 50.
Future<List<Purchase>> listMyPurchases(ApiClient client, String institutionId) {
  return client
      .request<List<dynamic>>('/institutions/${Uri.encodeComponent(institutionId)}/me/purchases')
      .then((list) => list.map((item) => Purchase.fromJson(item as Map<String, dynamic>)).toList());
}
