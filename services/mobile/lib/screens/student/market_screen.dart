/// Маркет привилегий ученика — перенос `services/web/src/pages/MarketPage.tsx`
/// (только ветка `student`; режим чтения для `teacher` — 09b).
///
/// **Политика `operation_id` переносится буквально** (`web-service/01-structure.md`,
/// риск 6 плана `09-mobile-app.md`): id заводится при первой попытке купить
/// конкретную привилегию и хранится в [pendingPurchasesProvider] (вне `State`
/// этого экрана — находка С3 ревью безопасности, план `09-mobile-app.md`,
/// Ч6) до успеха или до `PRICE_CHANGED` — при любом другом отказе (сеть,
/// таймаут, 5xx, `OUT_OF_STOCK`, `INSUFFICIENT_BALANCE`, …) повтор уходит с
/// тем же id, иначе возможно двойное списание.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/market_api.dart' as market_api;
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import 'formatting.dart';
import 'providers.dart';

/// Экран «Маркет» для роли `student`. Подключается роутером напрямую.
class MarketScreen extends ConsumerStatefulWidget {
  const MarketScreen({super.key});

  @override
  ConsumerState<MarketScreen> createState() => _MarketScreenState();
}

class _MarketScreenState extends ConsumerState<MarketScreen> {
  final Set<String> _buyingIds = {};
  final Map<String, Object> _buyErrors = {};

  Future<void> _handleBuy(market_api.Privilege privilege, InstitutionContext institution) async {
    setState(() => _buyErrors.remove(privilege.id));
    final confirmed = await showConfirmDialog(
      context,
      title: 'Купить «${privilege.title}»?',
      description: 'Цена: ${formatThousands(privilege.price)}'
          '${institution.currencyName != null ? ' ${institution.currencyName}' : ''}',
      confirmLabel: 'Купить',
    );
    if (confirmed != true || !mounted) return;
    await _performPurchase(privilege, institution);
  }

  Future<void> _performPurchase(market_api.Privilege privilege, InstitutionContext institution) async {
    // userId — из sessionProvider: экран открывается только authed, поэтому
    // user не null (см. router).
    final userId = ref.read(sessionProvider).user!.id;
    final key = PendingPurchaseKey(userId: userId, institutionId: institution.id, privilegeId: privilege.id);
    final pending = ref.read(pendingPurchasesProvider.notifier);
    final operationId = pending.take(key);
    setState(() => _buyingIds.add(privilege.id));

    final client = ref.read(apiClientProvider);
    try {
      await market_api.purchase(
        client,
        institution.id,
        operationId: operationId,
        privilegeId: privilege.id,
        expectedPrice: privilege.price,
      );
      pending.clear(key);
      if (!mounted) return;
      setState(() => _buyingIds.remove(privilege.id));
      ref.invalidate(studentCurrencyProvider);
      ref.invalidate(myPurchasesProvider);
      ref.invalidate(privilegesProvider);
      showSavedNotice(context);
    } catch (error) {
      // Новый id — только после `PRICE_CHANGED`: каталог перечитывается, и
      // следующая попытка обязана уйти с новой ценой и новым id. При любом
      // другом отказе id сохраняется — сервер мог уже закоммитить покупку.
      if (error is ApiError && error.code == 'PRICE_CHANGED') {
        pending.clear(key);
        ref.invalidate(privilegesProvider);
      }
      if (!mounted) return;
      setState(() {
        _buyingIds.remove(privilege.id);
        _buyErrors[privilege.id] = error;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final currencyName = institution?.currencyName;
    final accountAsync = ref.watch(studentCurrencyProvider);
    final privilegesAsync = ref.watch(privilegesProvider);
    final purchasesAsync = ref.watch(myPurchasesProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Маркет', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await Future.wait([
              ref.refresh(studentCurrencyProvider.future),
              ref.refresh(privilegesProvider.future),
              ref.refresh(myPurchasesProvider.future),
            ]);
          } catch (_) {
            // Ошибки каждого источника показываются на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            accountAsync.when(
              loading: () => const SizedBox.shrink(),
              error: (error, stackTrace) => const SizedBox.shrink(),
              data: (account) => Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: Row(
                  children: [
                    const Text('Баланс: '),
                    Money(amount: account.balance, size: 20),
                    if (currencyName != null) ...[const SizedBox(width: AppSpacing.xs), Text(currencyName)],
                  ],
                ),
              ),
            ),
            privilegesAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(privilegesProvider),
              ),
              data: (privileges) {
                if (privileges.isEmpty) {
                  return const ScreenStateEmpty(message: 'Учреждение ещё не добавило привилегии');
                }
                final balance = accountAsync.value?.balance;
                return Column(
                  children: [
                    for (final privilege in privileges)
                      _PrivilegeCard(
                        privilege: privilege,
                        currencyName: currencyName,
                        balance: balance,
                        buying: _buyingIds.contains(privilege.id),
                        error: _buyErrors[privilege.id],
                        onBuy: institution == null ? null : () => _handleBuy(privilege, institution),
                      ),
                  ],
                );
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            Text('МОИ ПОКУПКИ', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            purchasesAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
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

class _PrivilegeCard extends StatelessWidget {
  const _PrivilegeCard({
    required this.privilege,
    required this.currencyName,
    required this.balance,
    required this.buying,
    required this.error,
    required this.onBuy,
  });

  final market_api.Privilege privilege;
  final String? currencyName;

  /// `null`, пока баланс ещё не загружен — тогда кнопка «Купить» доступна,
  /// проверка нехватки средств делается сервером.
  final int? balance;
  final bool buying;
  final Object? error;
  final VoidCallback? onBuy;

  @override
  Widget build(BuildContext context) {
    final outOfStock = privilege.stock != null && privilege.stock! <= 0;
    final shortage = balance != null ? privilege.price - balance! : 0;
    final cannotAfford = balance != null && shortage > 0;

    String label = 'Купить';
    if (outOfStock) {
      label = 'Нет в наличии';
    } else if (cannotAfford) {
      label = 'Не хватает $shortage';
    }

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(privilege.title, style: const TextStyle(fontWeight: FontWeight.w600)),
            if (privilege.description != null) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(privilege.description!, style: const TextStyle(color: AppColors.textMuted)),
            ],
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Money(amount: privilege.price),
                if (currencyName != null) ...[const SizedBox(width: AppSpacing.xs), Text(currencyName!)],
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              privilege.stock == null ? 'Без ограничения' : 'Остаток: ${privilege.stock}',
              style: const TextStyle(color: AppColors.textMuted),
            ),
            if (error != null) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(messageForError(error!), style: const TextStyle(color: AppColors.danger)),
            ],
            const SizedBox(height: AppSpacing.sm),
            Align(
              alignment: Alignment.centerRight,
              child: OutlinedButton(
                onPressed: (outOfStock || cannotAfford || buying) ? null : onBuy,
                child: Text(buying ? 'Покупаем…' : label),
              ),
            ),
          ],
        ),
      ),
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
