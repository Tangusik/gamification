/// Карточка одной группы — зеркало `services/web/src/pages/GroupPage.tsx`:
/// переименование, удаление, преподаватели и ученики группы.
///
/// Отдельного `GET /groups/{groupId}` в контракте нет — группа находит себя в
/// списке [groupsProvider].
///
/// `teacher` получает тот же список (`require_admin_or_teacher` на бэкенде),
/// но экран здесь read-only: без формы переименования, без удаления и без
/// управления составом — те же данные, только без кнопок. Переход к карточке
/// ученика отсюда не делается — веб (`GroupPage.tsx`) тоже не ссылается на
/// учеников списка группы, только показывает имя.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart' show UserRole;
import '../../api/errors.dart';
import '../../api/groups_api.dart' as groups_api;
import '../../api/students_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/screen_state.dart';
import '../admin/teachers_providers.dart';
import '../common/form_feedback.dart';
import 'group_providers.dart';
import 'groups_providers.dart';

class GroupScreen extends ConsumerStatefulWidget {
  const GroupScreen({super.key, required this.groupId});

  final String groupId;

  @override
  ConsumerState<GroupScreen> createState() => _GroupScreenState();
}

class _GroupScreenState extends ConsumerState<GroupScreen> {
  final _nameController = TextEditingController();
  bool _nameInitialized = false;

  bool _renaming = false;
  ApiError? _renameError;

  bool _deleting = false;
  ApiError? _deleteError;

  String? _addTeacherId;
  String? _addStudentId;
  String? _busyMemberId;
  ApiError? _memberActionError;

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  void _refreshAfterMemberChange() {
    ref.invalidate(groupsProvider);
    ref.invalidate(teachersProvider);
    ref.invalidate(groupStudentsProvider(widget.groupId));
    ref.invalidate(allStudentsProvider);
  }

  Future<void> _handleRename() async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _renaming = true;
      _renameError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.updateGroup(client, institution.id, widget.groupId, _nameController.text);
      ref.invalidate(groupsProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _renameError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _renaming = false);
    }
  }

  Future<void> _handleDelete(int studentsInGroup) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Удалить группу?',
      description: 'Ученики и преподаватели не удаляются, только связь с группой. '
          'Учеников в группе: $studentsInGroup.',
      confirmLabel: 'Удалить',
      danger: true,
    );
    if (confirmed != true || !mounted) return;

    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _deleting = true;
      _deleteError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.deleteGroup(client, institution.id, widget.groupId);
      if (!mounted) return;
      // `Navigator.pop`, а не `context.pop` из go_router: экран уходит на
      // предыдущий маршрут в любом дереве, включая тесты без `GoRouter`.
      Navigator.of(context).pop();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _deleteError = error is ApiError ? error : const ApiError(0, unknownError);
        _deleting = false;
      });
    }
  }

  Future<void> _handleAddTeacher() async {
    final institution = ref.read(sessionProvider).institution;
    final userId = _addTeacherId;
    if (institution == null || userId == null || userId.isEmpty) return;
    setState(() {
      _busyMemberId = userId;
      _memberActionError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.addTeacherToGroup(client, institution.id, widget.groupId, userId);
      if (!mounted) return;
      setState(() => _addTeacherId = null);
      _refreshAfterMemberChange();
    } catch (error) {
      if (!mounted) return;
      setState(() => _memberActionError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _busyMemberId = null);
    }
  }

  Future<void> _handleRemoveTeacher(String userId) async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _busyMemberId = userId;
      _memberActionError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.removeTeacherFromGroup(client, institution.id, widget.groupId, userId);
      if (!mounted) return;
      _refreshAfterMemberChange();
    } catch (error) {
      if (!mounted) return;
      setState(() => _memberActionError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _busyMemberId = null);
    }
  }

  Future<void> _handleAddStudent() async {
    final institution = ref.read(sessionProvider).institution;
    final userId = _addStudentId;
    if (institution == null || userId == null || userId.isEmpty) return;
    setState(() {
      _busyMemberId = userId;
      _memberActionError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.addStudentToGroup(client, institution.id, widget.groupId, userId);
      if (!mounted) return;
      setState(() => _addStudentId = null);
      _refreshAfterMemberChange();
    } catch (error) {
      if (!mounted) return;
      setState(() => _memberActionError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _busyMemberId = null);
    }
  }

  // Убрать из группы — без подтверждения (раздел 7 плана 08, обратимо).
  Future<void> _handleRemoveStudent(String userId) async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _busyMemberId = userId;
      _memberActionError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await groups_api.removeStudentFromGroup(client, institution.id, widget.groupId, userId);
      if (!mounted) return;
      _refreshAfterMemberChange();
    } catch (error) {
      if (!mounted) return;
      setState(() => _memberActionError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _busyMemberId = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final groupsAsync = ref.watch(groupsProvider);

    groups_api.Group? group;
    groupsAsync.whenData((groups) {
      for (final item in groups) {
        if (item.id == widget.groupId) {
          group = item;
          break;
        }
      }
    });
    if (group != null && !_nameInitialized) {
      _nameController.text = group!.name;
      _nameInitialized = true;
    }

    return Scaffold(
      appBar: AppBar(title: Text(group?.name ?? 'Группа', style: Theme.of(context).textTheme.titleMedium)),
      body: groupsAsync.when(
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
          final found = group;
          if (found == null) {
            return const Padding(
              padding: EdgeInsets.all(AppSpacing.lg),
              child: Text('Группа не найдена.'),
            );
          }
          return _buildBody(context, found);
        },
      ),
    );
  }

  Widget _buildBody(BuildContext context, groups_api.Group group) {
    final institution = ref.watch(sessionProvider.select((state) => state.institution));
    final isAdmin = institution?.role == UserRole.institutionAdmin;
    final teachersAsync = ref.watch(teachersProvider);
    final groupStudentsAsync = ref.watch(groupStudentsProvider(widget.groupId));
    // Список всех учеников нужен только admin (выбор при добавлении) —
    // watch стоит под условием, чтобы teacher не тянул этот запрос вовсе.
    final allStudentsAsync = isAdmin ? ref.watch(allStudentsProvider) : null;

    return RefreshIndicator(
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
            TextField(
              controller: _nameController,
              enabled: !_renaming,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Название'),
            ),
            FormErrorText(_renameError == null ? null : messageForError(_renameError!)),
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton(
              onPressed: _renaming ? null : _handleRename,
              child: Text(_renaming ? 'Сохраняем…' : 'Переименовать'),
            ),
            const SizedBox(height: AppSpacing.md),
            OutlinedButton(
              onPressed: _deleting
                  ? null
                  : () => _handleDelete(groupStudentsAsync.value?.length ?? 0),
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.danger,
                side: const BorderSide(color: AppColors.danger),
              ),
              child: Text(_deleting ? 'Удаляем…' : 'Удалить группу'),
            ),
            FormErrorText(_deleteError == null ? null : messageForError(_deleteError!)),
            const SizedBox(height: AppSpacing.lg),
          ],
          Text('ПРЕПОДАВАТЕЛИ', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          teachersAsync.when(
            loading: () => const ScreenStateLoading(),
            error: (error, _) => ScreenStateError(
              message: messageForError(error),
              code: error is ApiError ? error.code : null,
              onRetry: () => ref.invalidate(teachersProvider),
            ),
            data: (teachers) {
              final groupTeachers = teachers.where((member) => group.teacherIds.contains(member.userId)).toList();
              final availableTeachers = teachers.where((member) => !group.teacherIds.contains(member.userId)).toList();
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (groupTeachers.isEmpty) const Text('В группе нет преподавателей.'),
                  for (final member in groupTeachers)
                    _MemberTile(
                      label: member.displayName ?? 'Без имени',
                      busy: _busyMemberId == member.userId,
                      onRemove: isAdmin ? () => _handleRemoveTeacher(member.userId) : null,
                    ),
                  if (isAdmin && availableTeachers.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    _AddMemberRow(
                      label: 'Добавить преподавателя',
                      value: _addTeacherId,
                      options: [for (final member in availableTeachers) (member.userId, member.displayName ?? 'Без имени')],
                      busy: _busyMemberId != null,
                      onChanged: (value) => setState(() => _addTeacherId = value),
                      onAdd: _handleAddTeacher,
                    ),
                  ],
                ],
              );
            },
          ),
          const SizedBox(height: AppSpacing.lg),
          Text('УЧЕНИКИ', style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: AppSpacing.sm),
          groupStudentsAsync.when(
            loading: () => const ScreenStateLoading(),
            error: (error, _) => ScreenStateError(
              message: messageForError(error),
              code: error is ApiError ? error.code : null,
              onRetry: () => ref.invalidate(groupStudentsProvider(widget.groupId)),
            ),
            data: (groupStudents) {
              final availableStudents = (allStudentsAsync?.value ?? const <StudentMember>[])
                  .where((member) => !member.groupIds.contains(widget.groupId))
                  .toList();
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (groupStudents.isEmpty) const Text('В группе нет учеников.'),
                  for (final member in groupStudents)
                    _MemberTile(
                      label: member.displayName ?? 'Без имени',
                      busy: _busyMemberId == member.userId,
                      onRemove: isAdmin ? () => _handleRemoveStudent(member.userId) : null,
                    ),
                  if (allStudentsAsync != null) ...[
                    if (allStudentsAsync.hasError)
                      ScreenStateError(
                        message: messageForError(allStudentsAsync.error!),
                        code: allStudentsAsync.error is ApiError ? (allStudentsAsync.error as ApiError).code : null,
                        onRetry: () => ref.invalidate(allStudentsProvider),
                      )
                    else if (allStudentsAsync.isLoading)
                      const ScreenStateLoading()
                    else if (availableStudents.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.sm),
                      _AddMemberRow(
                        label: 'Добавить ученика',
                        value: _addStudentId,
                        options: [for (final member in availableStudents) (member.userId, member.displayName ?? 'Без имени')],
                        busy: _busyMemberId != null,
                        onChanged: (value) => setState(() => _addStudentId = value),
                        onAdd: _handleAddStudent,
                      ),
                    ],
                  ],
                ],
              );
            },
          ),
          FormErrorText(_memberActionError == null ? null : messageForError(_memberActionError!)),
        ],
      ),
    );
  }
}

class _MemberTile extends StatelessWidget {
  const _MemberTile({required this.label, required this.busy, required this.onRemove});

  final String label;
  final bool busy;
  final VoidCallback? onRemove;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      contentPadding: EdgeInsets.zero,
      title: Text(label),
      trailing: onRemove == null
          ? null
          : OutlinedButton(onPressed: busy ? null : onRemove, child: const Text('Убрать')),
    );
  }
}

class _AddMemberRow extends StatelessWidget {
  const _AddMemberRow({
    required this.label,
    required this.value,
    required this.options,
    required this.busy,
    required this.onChanged,
    required this.onAdd,
  });

  final String label;
  final String? value;
  final List<(String, String)> options;
  final bool busy;
  final ValueChanged<String?> onChanged;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: DropdownButtonFormField<String>(
            initialValue: value,
            decoration: InputDecoration(labelText: label),
            onChanged: busy ? null : onChanged,
            items: [
              for (final option in options) DropdownMenuItem(value: option.$1, child: Text(option.$2)),
            ],
          ),
        ),
        const SizedBox(width: AppSpacing.sm),
        OutlinedButton(
          onPressed: (value == null || value!.isEmpty || busy) ? null : onAdd,
          child: const Text('Добавить'),
        ),
      ],
    );
  }
}
