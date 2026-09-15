/// Главная преподавателя и администратора — перенос веток
/// `AdminDashboard`/`TeacherDashboard` из `services/web/src/pages/HomePage.tsx`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show UserRole;
import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../router/paths.dart';
import '../../ui/design_tokens.dart';
import '../../ui/screen_state.dart';
import 'staff_home_providers.dart';
import 'students_providers.dart';

/// Экран «Главная» для ролей `teacher` и `institution_admin`. Подключается
/// роутером напрямую.
class StaffHomeScreen extends ConsumerWidget {
  const StaffHomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));

    return Scaffold(
      appBar: AppBar(title: Text('Главная', style: Theme.of(context).textTheme.titleMedium)),
      body: institution == null
          ? const ScreenStateLoading()
          : institution.role == UserRole.institutionAdmin
              ? const _AdminHome()
              : const _TeacherHome(),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton(onPressed: onPressed, child: Text(label));
  }
}

class _AdminHome extends ConsumerWidget {
  const _AdminHome();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pendingAsync = ref.watch(staffPendingPurchasesProvider);

    return RefreshIndicator(
      onRefresh: () async {
        try {
          final _ = await ref.refresh(staffPendingPurchasesProvider.future);
        } catch (_) {
          // Ошибка показывается на месте ниже.
        }
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              _ActionButton(label: 'Начислить валюту', onPressed: () => context.go(studentsPath)),
              _ActionButton(label: 'Пригласить ученика', onPressed: () => context.push(invitationsPath)),
              _ActionButton(label: 'Добавить преподавателя', onPressed: () => context.push(teachersPath)),
              _ActionButton(label: 'Создать группу', onPressed: () => context.push(groupsPath)),
              _ActionButton(label: 'Добавить привилегию', onPressed: () => context.push(marketPrivilegesPath)),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('ЗАЯВКИ', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: AppSpacing.sm),
                  pendingAsync.when(
                    loading: () => const ScreenStateLoading(),
                    error: (error, _) => ScreenStateError(
                      message: messageForError(error),
                      code: error is ApiError ? error.code : null,
                      onRetry: () => ref.invalidate(staffPendingPurchasesProvider),
                    ),
                    data: (count) => Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Заявки на выдачу: $count'),
                        const SizedBox(height: AppSpacing.sm),
                        OutlinedButton(
                          onPressed: () => context.go(marketPurchasesPath),
                          child: const Text('Все заявки'),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _TeacherHome extends ConsumerWidget {
  const _TeacherHome();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final groupsAsync = ref.watch(staffGroupsProvider);

    return RefreshIndicator(
      onRefresh: () async {
        try {
          final _ = await ref.refresh(staffGroupsProvider.future);
        } catch (_) {
          // Ошибка показывается на месте ниже.
        }
      },
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.all(AppSpacing.lg),
        children: [
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            children: [
              _ActionButton(label: 'Начислить валюту', onPressed: () => context.go(studentsPath)),
              _ActionButton(label: 'Пригласить ученика', onPressed: () => context.push(invitationsPath)),
            ],
          ),
          const SizedBox(height: AppSpacing.lg),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('МОИ ГРУППЫ', style: Theme.of(context).textTheme.titleMedium),
                  const SizedBox(height: AppSpacing.sm),
                  groupsAsync.when(
                    loading: () => const ScreenStateLoading(),
                    error: (error, _) => ScreenStateError(
                      message: messageForError(error),
                      code: error is ApiError ? error.code : null,
                      onRetry: () => ref.invalidate(staffGroupsProvider),
                    ),
                    data: (groups) {
                      if (groups.isEmpty) {
                        return const Text(
                          'В ваших группах нет учеников. Состав групп задаёт администратор',
                          style: TextStyle(color: AppColors.textMuted),
                        );
                      }
                      return Column(
                        children: [
                          for (final group in groups)
                            ListTile(
                              contentPadding: EdgeInsets.zero,
                              title: Text(group.name),
                              trailing: Text(
                                'учеников: ${group.studentsCount}',
                                style: const TextStyle(color: AppColors.textMuted),
                              ),
                              onTap: () => context.push(groupPath(group.id)),
                            ),
                        ],
                      );
                    },
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
