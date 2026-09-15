/// Преподаватели учреждения — `institution_admin`, зеркало
/// `services/web/src/pages/TeachersPage.tsx`: создание, список, правка имени
/// и статуса.
///
/// Роутер уже ограничивает `/teachers` ролью admin (`lib/router/paths.dart`),
/// но сервер может ответить 403 и здесь (например, роль сменилась в другой
/// вкладке) — тогда список и форма создания уступают место
/// [ScreenStateForbidden] вместо падения.
///
/// UUID на экран не выводится — только имя (или «Без имени») и метаданные.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart' show MembershipStatus;
import '../../api/errors.dart';
import '../../api/teachers_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';
import 'teachers_providers.dart';

/// `дд.мм.гггг` без времени — как `toLocaleDateString('ru-RU')` веба.
String _formatDate(DateTime value) {
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}.${two(local.month)}.${local.year}';
}

class TeachersScreen extends ConsumerStatefulWidget {
  const TeachersScreen({super.key});

  @override
  ConsumerState<TeachersScreen> createState() => _TeachersScreenState();
}

class _TeachersScreenState extends ConsumerState<TeachersScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _displayNameController = TextEditingController();
  bool _creating = false;
  ApiError? _createError;

  String? _savingId;
  ApiError? _saveError;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    _displayNameController.dispose();
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
      await createTeacher(
        client,
        institution.id,
        CreateTeacherInput(
          email: _emailController.text,
          password: _passwordController.text,
          displayName: _displayNameController.text,
        ),
      );
      _emailController.clear();
      _passwordController.clear();
      _displayNameController.clear();
      ref.invalidate(teachersProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _createError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _applyUpdate(InstitutionMember member, UpdateMemberInput input, {bool showSaved = false}) async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _savingId = member.userId;
      _saveError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await updateTeacher(client, institution.id, member.userId, input);
      if (!mounted) return;
      ref.invalidate(teachersProvider);
      if (showSaved) showSavedNotice(context);
    } catch (error) {
      if (!mounted) return;
      setState(() => _saveError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _savingId = null);
    }
  }

  Future<void> _handleRename(InstitutionMember member, String nextName) async {
    final trimmed = nextName.trim();
    if (trimmed.isEmpty) return;
    await _applyUpdate(member, UpdateMemberInput(displayName: trimmed), showSaved: true);
  }

  Future<void> _handleStatusChange(InstitutionMember member, MembershipStatus status) async {
    if (status == MembershipStatus.suspended) {
      final confirmed = await showConfirmDialog(
        context,
        title: 'Приостановить преподавателя?',
        description: 'Доступ пропадёт сразу.',
        confirmLabel: 'Приостановить',
        danger: true,
      );
      if (confirmed != true || !mounted) return;
    }
    await _applyUpdate(member, UpdateMemberInput(status: status));
  }

  @override
  Widget build(BuildContext context) {
    final teachersAsync = ref.watch(teachersProvider);
    final fieldErrors = _createError?.fieldErrors;
    final emailFieldError = _createError?.code == 'EMAIL_ALREADY_REGISTERED'
        ? messageForCode('EMAIL_ALREADY_REGISTERED')
        : fieldErrors?['email'];
    final formError = _createError != null && fieldErrors == null && _createError!.code != 'EMAIL_ALREADY_REGISTERED'
        ? messageForError(_createError!)
        : null;

    return Scaffold(
      appBar: AppBar(title: Text('Преподаватели', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(teachersProvider.future);
          } catch (_) {
            // Ошибка показывается на месте ниже.
          }
        },
        child: ListView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    TextField(
                      controller: _emailController,
                      enabled: !_creating,
                      keyboardType: TextInputType.emailAddress,
                      decoration: const InputDecoration(labelText: 'Почта'),
                    ),
                    FieldErrorText(emailFieldError),
                    const SizedBox(height: AppSpacing.sm),
                    TextField(
                      controller: _passwordController,
                      enabled: !_creating,
                      decoration: const InputDecoration(labelText: 'Временный пароль'),
                    ),
                    FieldErrorText(fieldErrors?['password']),
                    const SizedBox(height: AppSpacing.sm),
                    TextField(
                      controller: _displayNameController,
                      enabled: !_creating,
                      maxLength: 100,
                      decoration: const InputDecoration(labelText: 'Имя'),
                    ),
                    FieldErrorText(fieldErrors?['display_name']),
                    FormErrorText(formError),
                    const SizedBox(height: AppSpacing.sm),
                    OutlinedButton(
                      onPressed: _creating ? null : _handleCreate,
                      child: Text(_creating ? 'Создаём…' : 'Добавить преподавателя'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            teachersAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) {
                if (error is ApiError && error.status == 403) return const ScreenStateForbidden();
                return ScreenStateError(
                  message: messageForError(error),
                  code: error is ApiError ? error.code : null,
                  onRetry: () => ref.invalidate(teachersProvider),
                );
              },
              data: (teachers) {
                if (teachers.isEmpty) {
                  return const ScreenStateEmpty(message: 'Преподавателей пока нет.');
                }
                return Column(
                  children: [
                    for (final member in teachers)
                      _TeacherCard(
                        key: ValueKey(member.userId),
                        member: member,
                        busy: _savingId == member.userId,
                        onSave: (name) => _handleRename(member, name),
                        onStatusChange: (status) => _handleStatusChange(member, status),
                      ),
                  ],
                );
              },
            ),
            FormErrorText(_saveError == null ? null : messageForError(_saveError!)),
          ],
        ),
      ),
    );
  }
}

class _TeacherCard extends StatefulWidget {
  const _TeacherCard({super.key, required this.member, required this.busy, required this.onSave, required this.onStatusChange});

  final InstitutionMember member;
  final bool busy;
  final ValueChanged<String> onSave;
  final ValueChanged<MembershipStatus> onStatusChange;

  @override
  State<_TeacherCard> createState() => _TeacherCardState();
}

class _TeacherCardState extends State<_TeacherCard> {
  late final TextEditingController _nameController;

  @override
  void initState() {
    super.initState();
    _nameController = TextEditingController(text: widget.member.displayName ?? '');
  }

  @override
  void dispose() {
    _nameController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final member = widget.member;
    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _nameController,
              enabled: !widget.busy,
              maxLength: 100,
              decoration: const InputDecoration(labelText: 'Имя', hintText: 'Без имени'),
            ),
            Text(
              'групп: ${member.groupIds.length} · создан ${_formatDate(member.createdAt)}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
            ),
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton(
                    onPressed: widget.busy ? null : () => widget.onSave(_nameController.text),
                    child: const Text('Сохранить имя'),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                DropdownButton<MembershipStatus>(
                  value: member.status == MembershipStatus.invited ? null : member.status,
                  hint: Text(statusLabels[member.status] ?? ''),
                  onChanged: widget.busy
                      ? null
                      : (value) {
                          if (value != null) widget.onStatusChange(value);
                        },
                  items: [
                    for (final status in [MembershipStatus.active, MembershipStatus.suspended])
                      DropdownMenuItem(value: status, child: Text(statusLabels[status] ?? '')),
                  ],
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
