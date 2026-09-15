/// Главная ученика — перенос ветки `StudentDashboard` в
/// `services/web/src/pages/HomePage.tsx`: баланс, последние 5 операций,
/// переход в маркет.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/currency_api.dart';
import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/screen_state.dart';
import 'formatting.dart';
import 'providers.dart';

/// Экран «Главная» для роли `student`. Подключается роутером напрямую.
class StudentHomeScreen extends ConsumerWidget {
  const StudentHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currencyName = ref.watch(sessionProvider.select((state) => state.institution?.currencyName));
    final accountAsync = ref.watch(studentCurrencyProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Главная', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(studentCurrencyProvider.future);
          } catch (_) {
            // Экран покажет ошибку сам, через AsyncValue ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            accountAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(studentCurrencyProvider),
              ),
              data: (account) => _HomeContent(account: account, currencyName: currencyName),
            ),
          ],
        ),
      ),
    );
  }
}

class _HomeContent extends StatelessWidget {
  const _HomeContent({required this.account, required this.currencyName});

  final CurrencyAccount account;
  final String? currencyName;

  @override
  Widget build(BuildContext context) {
    final recent = account.transactions.take(5).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('БАЛАНС', style: Theme.of(context).textTheme.titleMedium),
                const SizedBox(height: AppSpacing.sm),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.baseline,
                  textBaseline: TextBaseline.alphabetic,
                  children: [
                    Money(amount: account.balance, size: 24),
                    if (currencyName != null) ...[
                      const SizedBox(width: AppSpacing.xs),
                      Text(currencyName!, style: const TextStyle(color: AppColors.textMuted)),
                    ],
                  ],
                ),
                const SizedBox(height: AppSpacing.md),
                OutlinedButton(
                  onPressed: () => context.go('/market'),
                  child: const Text('В маркет'),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.lg),
        Text('ОПЕРАЦИИ', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: AppSpacing.sm),
        if (recent.isEmpty)
          const ScreenStateEmpty(message: 'Операций пока нет.')
        else
          Card(
            child: Column(
              children: [
                for (final transaction in recent) _TransactionTile(transaction: transaction),
              ],
            ),
          ),
      ],
    );
  }
}

class _TransactionTile extends StatelessWidget {
  const _TransactionTile({required this.transaction});

  final CurrencyTransaction transaction;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      title: Text(transactionKindLabels[transaction.kind] ?? ''),
      subtitle: Text(formatDateTime(transaction.createdAt)),
      trailing: Money(amount: transaction.amount, showPlus: true),
    );
  }
}
