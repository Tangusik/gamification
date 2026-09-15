/// Группы учреждения — зеркало `services/web/src/pages/GroupsPage.tsx`.
///
/// `institution_admin` — создание и переход в карточку группы. `teacher`
/// получает тот же список (сервер разрешает `require_admin_or_teacher`), но
/// видит только список, без формы создания — карточка группы для него тоже
/// read-only ([GroupScreen]).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show UserRole;
import '../../api/errors.dart';
import '../../api/groups_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../router/paths.dart';
import '../../ui/design_tokens.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';
import 'groups_providers.dart';

class GroupsScreen extends ConsumerStatefulWidget {
  const GroupsScreen({super.key});

  @override
  ConsumerState<GroupsScreen> createState() => _GroupsScreenState();
}

class _GroupsScreenState extends ConsumerState<GroupsScreen> {
  final _nameController = TextEditingController();
  bool _creating = false;
  ApiError? _createError;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  Future<void> _handleCreate() async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _creating = true;
      _createError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await createGroup(client, institution.id, _nameController.text);
      _nameController.clear();
      ref.invalidate(groupsProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _createError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final isAdmin = institution?.role == UserRole.institutionAdmin;
    final groupsAsync = ref.watch(groupsProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Группы', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(groupsProvider.future);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            if (isAdmin) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.md),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      TextField(
                        controller: _nameController,
                        enabled: !_creating,
                        maxLength: 100,
                        decoration: const InputDecoration(labelText: 'Название группы'),
                      ),
                      FormErrorText(_createError == null ? null : messageForError(_createError!)),
                      const SizedBox(height: AppSpacing.sm),
                      OutlinedButton(
                        onPressed: _creating ? null : _handleCreate,
                        child: Text(_creating ? 'Создаём…' : 'Создать группу'),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: AppSpacing.lg),
            ],
            groupsAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) {
                if (error is ApiError && error.status == 403) return const ScreenStateForbidden();
                return ScreenStateError(
                  message: messageForError(error),
                  code: error is ApiError ? error.code : null,
                  onRetry: () => ref.invalidate(groupsProvider),
                );
              },
              data: (groups) {
                if (groups.isEmpty) {
                  return const ScreenStateEmpty(message: 'Групп пока нет.');
                }
                return Column(
                  children: [for (final group in groups) _GroupCard(group: group)],
                );
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _GroupCard extends StatelessWidget {
  const _GroupCard({required this.group});

  final Group group;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: ListTile(
        title: Text(group.name),
        subtitle: Text('Преподавателей: ${group.teacherIds.length} · учеников: ${group.studentsCount}'),
        trailing: const Icon(Icons.chevron_right),
        onTap: () => context.push(groupPath(group.id)),
      ),
    );
  }
}
