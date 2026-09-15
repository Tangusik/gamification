/// Заявки на выдачу (admin) — перенос `services/web/src/pages/PurchasesPage.tsx`.
///
/// Очередь `pending` — отдельный запрос без лимита (У8), «История» — второй
/// запрос без фильтра (последние 50), из которого на клиенте вычитаются
/// записи `pending` (тот же приём, что в вебе — отдельного фильтра «история»
/// в контракте нет).
///
/// Оба решения подтверждаются диалогом (В7): «Выдать» прямо говорит, что
/// выдачу нельзя отменить; «Отклонить» — что валюта вернётся ученику.
/// `lib/ui/confirm_dialog.dart` (общий файл, не трогается) закрывается сразу
/// по выбору — в отличие от веба, где `ConfirmDialog` умеет висеть открытым и
/// показывать ошибку внутри себя, здесь ошибка решения показывается баннером
/// над очередью: карточка конкретной заявки может исчезнуть из списка сразу
/// же после перечитывания (например, при `PURCHASE_ALREADY_RESOLVED` заявку
/// уже решили без нас), и инлайн-ошибка на карточке потерялась бы вместе с
/// ней.
/// Кнопки на время запроса заблокированы (`_actingId`) — двойное нажатие не
/// шлёт второй запрос. После любого исхода (успех или ошибка, включая
/// `PURCHASE_ALREADY_RESOLVED`) список перечитывается и счётчик заявок в
/// меню — `pendingPurchasesCountProvider` — инвалидируется.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/market_admin_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';
import '../student/formatting.dart' show formatDateTime;
import 'pending_count.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final _pendingPurchasesProvider = FutureProvider.autoDispose<List<Purchase>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPurchases(client, institution.id, filter: const ListPurchasesFilter(status: PurchaseStatus.pending));
}, retry: _noRetry);

final _recentPurchasesProvider = FutureProvider.autoDispose<List<Purchase>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPurchases(client, institution.id);
}, retry: _noRetry);

class PurchasesScreen extends ConsumerStatefulWidget {
  const PurchasesScreen({super.key});

  @override
  ConsumerState<PurchasesScreen> createState() => _PurchasesScreenState();
}

class _PurchasesScreenState extends ConsumerState<PurchasesScreen> {
  String? _actingId;
  bool _actingFulfil = false;
  Object? _actionError;

  Future<void> _handleFulfil(Purchase purchase, String institutionId) async {
    setState(() => _actionError = null);
    final confirmed = await showConfirmDialog(
      context,
      title: 'Выдать «${purchase.title}»?',
      description: 'Выдачу отменить нельзя.',
      confirmLabel: 'Выдать',
    );
    if (confirmed != true || !mounted) return;
    await _performAction(purchase, institutionId, fulfil: true);
  }

  Future<void> _handleReject(Purchase purchase, String institutionId) async {
    setState(() => _actionError = null);
    final confirmed = await showConfirmDialog(
      context,
      title: 'Отклонить «${purchase.title}»?',
      description: 'Валюта вернётся ученику.',
      confirmLabel: 'Отклонить',
      danger: true,
    );
    if (confirmed != true || !mounted) return;
    await _performAction(purchase, institutionId, fulfil: false);
  }

  Future<void> _performAction(Purchase purchase, String institutionId, {required bool fulfil}) async {
    setState(() {
      _actingId = purchase.id;
      _actingFulfil = fulfil;
    });
    final client = ref.read(apiClientProvider);
    try {
      if (fulfil) {
        await fulfilPurchase(client, institutionId, purchase.id);
      } else {
        await rejectPurchase(client, institutionId, purchase.id);
      }
      ref.invalidate(_pendingPurchasesProvider);
      ref.invalidate(_recentPurchasesProvider);
      ref.invalidate(pendingPurchasesCountProvider);
      if (!mounted) return;
      setState(() => _actingId = null);
    } catch (error) {
      // Список перечитывается и после ошибки: код вроде
      // `PURCHASE_ALREADY_RESOLVED` означает, что состояние на сервере уже
      // другое — заявка могла быть решена без нашего участия.
      ref.invalidate(_pendingPurchasesProvider);
      ref.invalidate(_recentPurchasesProvider);
      ref.invalidate(pendingPurchasesCountProvider);
      if (!mounted) return;
      setState(() {
        _actingId = null;
        _actionError = error;
      });
    }
  }

  void _retry() {
    ref.invalidate(_pendingPurchasesProvider);
    ref.invalidate(_recentPurchasesProvider);
  }

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final pendingAsync = ref.watch(_pendingPurchasesProvider);
    final recentAsync = ref.watch(_recentPurchasesProvider);
    final pendingCount = pendingAsync.value?.length;

    return Scaffold(
      appBar: AppBar(
        title: Text(
          pendingCount != null ? 'Заявки ($pendingCount)' : 'Заявки',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            await Future.wait([
              ref.refresh(_pendingPurchasesProvider.future),
              ref.refresh(_recentPurchasesProvider.future),
            ]);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            FormErrorText(_actionError == null ? null : messageForError(_actionError!)),
            pendingAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: _retry,
              ),
              data: (pending) {
                if (pending.isEmpty) {
                  return const ScreenStateEmpty(message: 'Новых заявок нет');
                }
                return Column(
                  children: [
                    for (final purchase in pending)
                      _PendingPurchaseCard(
                        purchase: purchase,
                        actingFulfil: _actingId == purchase.id && _actingFulfil,
                        actingReject: _actingId == purchase.id && !_actingFulfil,
                        busy: _actingId != null,
                        onFulfil: institution == null ? null : () => _handleFulfil(purchase, institution.id),
                        onReject: institution == null ? null : () => _handleReject(purchase, institution.id),
                      ),
                  ],
                );
              },
            ),
            const SizedBox(height: AppSpacing.lg),
            Text('ИСТОРИЯ', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.sm),
            recentAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: _retry,
              ),
              data: (recent) {
                final history = recent.where((item) => item.status != PurchaseStatus.pending).toList();
                if (history.isEmpty) {
                  return const ScreenStateEmpty(message: 'Решённых покупок пока нет');
                }
                return Card(
                  child: Column(
                    children: [for (final purchase in history) _HistoryTile(purchase: purchase)],
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

class _PendingPurchaseCard extends StatelessWidget {
  const _PendingPurchaseCard({
    required this.purchase,
    required this.actingFulfil,
    required this.actingReject,
    required this.busy,
    required this.onFulfil,
    required this.onReject,
  });

  final Purchase purchase;

  /// Идёт запрос именно по этой заявке и именно на выдачу/отказ.
  final bool actingFulfil;
  final bool actingReject;

  /// Идёт запрос по любой заявке — блокирует остальные кнопки, чтобы не
  /// уйти сразу в два одновременных решения.
  final bool busy;
  final VoidCallback? onFulfil;
  final VoidCallback? onReject;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(purchase.title, style: const TextStyle(fontWeight: FontWeight.w600)),
            const SizedBox(height: AppSpacing.xs),
            Money(amount: purchase.price),
            const SizedBox(height: AppSpacing.xs),
            Text(purchase.userName ?? 'Без имени', style: const TextStyle(color: AppColors.textMuted)),
            Text(formatDateTime(purchase.createdAt), style: const TextStyle(color: AppColors.textMuted)),
            const SizedBox(height: AppSpacing.sm),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                OutlinedButton(
                  onPressed: busy ? null : onReject,
                  style: OutlinedButton.styleFrom(
                    foregroundColor: AppColors.danger,
                    side: const BorderSide(color: AppColors.danger),
                  ),
                  child: Text(actingReject ? 'Сохраняем…' : 'Отклонить'),
                ),
                const SizedBox(width: AppSpacing.sm),
                OutlinedButton(
                  onPressed: busy ? null : onFulfil,
                  child: Text(actingFulfil ? 'Сохраняем…' : 'Выдать'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _HistoryTile extends StatelessWidget {
  const _HistoryTile({required this.purchase});

  final Purchase purchase;

  @override
  Widget build(BuildContext context) {
    final resolvedAt = purchase.resolvedAt;
    return ListTile(
      title: Text('${purchase.title} — ${purchase.userName ?? 'Без имени'}'),
      subtitle: Text(
        '${purchaseStatusLabels[purchase.status] ?? ''}'
        '${resolvedAt != null ? ' · ${formatDateTime(resolvedAt)}' : ''}',
      ),
      trailing: Money(amount: purchase.price),
    );
  }
}
