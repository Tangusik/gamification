/// История операций ученика — объединение `services/web/src/pages/MyBalancePage.tsx`
/// (операции по валюте) и раздела «Мои покупки» из `MarketPage.tsx`. На
/// телефоне это две секции одного скролла, а не отдельные страницы веба —
/// заголовки различают их вместо переходов по ссылкам.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/currency_api.dart';
import '../../api/errors.dart';
import '../../api/market_api.dart' as market_api;
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/screen_state.dart';
import 'formatting.dart';
import 'providers.dart';

/// Экран «История» для роли `student`. Подключается роутером напрямую.
class HistoryScreen extends ConsumerWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final accountAsync = ref.watch(studentCurrencyProvider);
    final purchasesAsync = ref.watch(myPurchasesProvider);

    return Scaffold(
      appBar: AppBar(title: Text('История', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await Future.wait([
              ref.refresh(studentCurrencyProvider.future),
              ref.refresh(myPurchasesProvider.future),
            ]);
          } catch (_) {
            // Ошибки каждой секции показываются на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Text('ОПЕРАЦИИ ПО ВАЛЮТЕ', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            accountAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, stackTrace) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(studentCurrencyProvider),
              ),
              data: (account) {
                if (account.transactions.isEmpty) {
                  return const ScreenStateEmpty(message: 'Операций пока нет');
                }
                return Card(
                  child: Column(
                    children: [
                      for (final transaction in account.transactions)
                        _TransactionTile(transaction: transaction),
                    ],
                  ),
                );
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            Text('МОИ ПОКУПКИ', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            purchasesAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, stackTrace) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(myPurchasesProvider),
              ),
              data: (purchases) {
                if (purchases.isEmpty) {
                  return const ScreenStateEmpty(message: 'Покупок пока нет');
                }
                return Card(
                  child: Column(
                    children: [for (final purchase in purchases) _PurchaseTile(purchase: purchase)],
                  ),
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _TransactionTile extends StatelessWidget {
  const _TransactionTile({required this.transaction});

  final CurrencyTransaction transaction;

  @override
  Widget build(BuildContext context) {
    final author = transaction.createdByName ?? roleLabels[transaction.createdByRole] ?? '';
    final comment = transaction.comment;
    return ListTile(
      title: Text(transactionKindLabels[transaction.kind] ?? ''),
      subtitle: Text(
        '$author · ${formatDateTime(transaction.createdAt)}'
        '${comment != null ? ' · $comment' : ''}',
      ),
      trailing: Money(amount: transaction.amount, showPlus: true),
    );
  }
}

class _PurchaseTile extends StatelessWidget {
  const _PurchaseTile({required this.purchase});

  final market_api.Purchase purchase;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      title: Text('${purchase.title} — ${formatThousands(purchase.price)}'),
      subtitle: Text('${purchaseStatusLabels[purchase.status] ?? ''} · ${formatDateTime(purchase.createdAt)}'),
    );
  }
}
