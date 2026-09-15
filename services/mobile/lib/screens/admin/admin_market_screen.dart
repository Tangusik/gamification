/// Вкладка «Маркет» администратора — вход в раздел с двумя вложенными
/// пунктами: «Каталог» (`marketPrivilegesPath`) и «Заявки»
/// (`marketPurchasesPath`, с числом заявок `pending` рядом — то же число, что
/// и бейдж вкладки в `_AppShell`, источник — `pendingPurchasesCountProvider`).
///
/// Роутер уже ограничивает оба вложенных пути ролью `institution_admin`
/// (`lib/router/app_router.dart`), здесь дополнительная проверка не нужна.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../router/paths.dart';
import '../../ui/design_tokens.dart';
import 'pending_count.dart';

class AdminMarketScreen extends ConsumerWidget {
  const AdminMarketScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pendingCount = ref.watch(pendingPurchasesCountProvider).value;

    return Scaffold(
      appBar: AppBar(title: Text('Маркет', style: Theme.of(context).textTheme.titleMedium)),
      body: ListView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Card(
            child: ListTile(
              leading: const Icon(Icons.storefront_outlined),
              title: const Text('Каталог'),
              subtitle: const Text('Позиции, цены и остатки'),
              trailing: const Icon(Icons.chevron_right),
              onTap: () => context.push(marketPrivilegesPath),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
          Card(
            child: ListTile(
              leading: const Icon(Icons.assignment_outlined),
              title: const Text('Заявки'),
              subtitle: const Text('Выдача и отклонение покупок'),
              trailing: pendingCount != null && pendingCount > 0
                  ? Badge(label: Text('$pendingCount'), child: const Icon(Icons.chevron_right))
                  : const Icon(Icons.chevron_right),
              onTap: () => context.push(marketPurchasesPath),
            ),
          ),
        ],
      ),
    );
  }
}
