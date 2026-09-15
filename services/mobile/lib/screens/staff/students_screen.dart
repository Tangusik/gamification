/// Список учеников (teacher, admin) — перенос
/// `services/web/src/pages/StudentsPage.tsx`: карточки вместо таблицы,
/// фильтр по группе и поиск по имени на клиенте.
///
/// `institution_admin` видит всех учеников учреждения, `teacher` — только
/// учеников своих групп (фильтрует сервер). UUID на экран не выводится —
/// только имя («Без имени», если `display_name` не задан) и баланс.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show UserRole;
import '../../api/errors.dart';
import '../../api/groups_api.dart' show Group;
import '../../api/students_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../router/paths.dart';
import '../../ui/design_tokens.dart';
import '../../ui/money.dart';
import '../../ui/screen_state.dart';
import 'students_providers.dart';

/// Экран «Ученики» для ролей `teacher` и `institution_admin`. Подключается
/// роутером напрямую.
class StudentsScreen extends ConsumerStatefulWidget {
  const StudentsScreen({super.key});

  @override
  ConsumerState<StudentsScreen> createState() => _StudentsScreenState();
}

class _StudentsScreenState extends ConsumerState<StudentsScreen> {
  String _groupFilter = '';
  String _search = '';

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final isAdmin = institution?.role == UserRole.institutionAdmin;
    final studentsAsync = ref.watch(studentsListProvider);
    final groupsAsync = ref.watch(staffGroupsProvider);
    final groups = groupsAsync.value;

    return Scaffold(
      appBar: AppBar(title: Text('Ученики', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            await Future.wait([
              ref.refresh(studentsListProvider.future),
              ref.refresh(staffGroupsProvider.future),
            ]);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if ((groups ?? const []).isNotEmpty) ...[
              DropdownButtonFormField<String>(
                initialValue: _groupFilter,
                decoration: const InputDecoration(labelText: 'Группа'),
                items: [
                  const DropdownMenuItem(value: '', child: Text('Все')),
                  for (final group in groups!)
                    DropdownMenuItem(value: group.id, child: Text(group.name)),
                ],
                onChanged: (value) => setState(() => _groupFilter = value ?? ''),
              ),
              const SizedBox(height: AppSpacing.md),
            ],
            TextField(
              decoration: const InputDecoration(labelText: 'Поиск по имени', hintText: 'Начните вводить имя…'),
              onChanged: (value) => setState(() => _search = value),
            ),
            const SizedBox(height: AppSpacing.md),
            studentsAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) => ScreenStateError(
                message: messageForError(error),
                code: error is ApiError ? error.code : null,
                onRetry: () => ref.invalidate(studentsListProvider),
              ),
              data: (students) {
                if (students.isEmpty) {
                  return ScreenStateEmpty(
                    message: isAdmin
                        ? 'Учеников пока нет.'
                        : 'В ваших группах нет учеников. Состав групп задаёт администратор.',
                    action: isAdmin
                        ? OutlinedButton(
                            onPressed: () => context.push(invitationsPath),
                            child: const Text('Создать ссылку-приглашение'),
                          )
                        : null,
                  );
                }

                final filtered = students.where((student) {
                  if (_groupFilter.isNotEmpty && !student.groupIds.contains(_groupFilter)) return false;
                  final query = _search.trim().toLowerCase();
                  if (query.isEmpty) return true;
                  return (student.displayName ?? '').toLowerCase().contains(query);
                }).toList();

                if (filtered.isEmpty) {
                  return const Padding(
                    padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
                    child: Text('Никого не нашлось.', style: TextStyle(color: AppColors.textMuted)),
                  );
                }

                return Column(
                  children: [
                    for (final student in filtered)
                      _StudentCard(
                        student: student,
                        groups: groups,
                        isAdmin: isAdmin,
                        onTap: () => context.push(studentCardPath(student.userId)),
                      ),
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

class _StudentCard extends StatelessWidget {
  const _StudentCard({required this.student, required this.groups, required this.isAdmin, required this.onTap});

  final StudentMember student;
  final List<Group>? groups;
  final bool isAdmin;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final groupsLabel = student.groupIds.isEmpty
        ? 'без группы'
        : student.groupIds.map((id) => groupNameOrDash(groups, id)).join(', ');

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: ListTile(
        title: Text(student.displayName ?? (isAdmin ? 'Задать имя' : 'Без имени')),
        subtitle: Text(groupsLabel, style: const TextStyle(color: AppColors.textMuted)),
        trailing: Money(amount: student.balance),
        onTap: onTap,
      ),
    );
  }
}
