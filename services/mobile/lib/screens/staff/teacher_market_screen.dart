/// Маркет преподавателя — каталог только на чтение (В14/б), перенос ветки
/// `teacher` из `services/web/src/pages/MarketPage.tsx`.
///
/// Без баланса, без покупки и без «моих покупок»: ни `GET /me/currency`, ни
/// `GET /me/purchases`, ни `POST /purchases` для этой роли не выполняются —
/// только `GET /privileges`, который сервер и так отдаёт учителю в урезанном
/// виде (только активные позиции).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/market_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/screen_state.dart';

Duration? _noRetry(int retryCount, Object error) => null;

final _teacherPrivilegesProvider = FutureProvider.autoDispose<List<Privilege>>((ref) async {
  final institution = ref.watch(sessionProvider.select((state) => state.institution));
  if (institution == null) {
    throw StateError('Учреждение не выбрано');
  }
  final client = ref.watch(apiClientProvider);
  return listPrivileges(client, institution.id);
}, retry: _noRetry);

/// Экран «Маркет» для роли `teacher`. Подключается роутером напрямую.
class TeacherMarketScreen extends ConsumerWidget {
  const TeacherMarketScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final currencyName = ref.watch(sessionProvider.select((state) => state.institution?.currencyName));
    final privilegesAsync = ref.watch(_teacherPrivilegesProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Маркет', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(_teacherPrivilegesProvider.future);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            privilegesAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(_teacherPrivilegesProvider),
              ),
              data: (privileges) {
                if (privileges.isEmpty) {
                  return const ScreenStateEmpty(message: 'Учреждение ещё не добавило привилегии');
                }
                return Column(
                  children: [
                    for (final privilege in privileges)
                      _ReadOnlyPrivilegeCard(privilege: privilege, currencyName: currencyName),
                  ],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _ReadOnlyPrivilegeCard extends StatelessWidget {
  const _ReadOnlyPrivilegeCard({required this.privilege, required this.currencyName});

  final Privilege privilege;
  final String? currencyName;

  @override
  Widget build(BuildContext context) {
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
          ],
        ),
      ),
    );
  }
}
