/// Профиль пользователя — вкладка «Профиль», зеркало
/// `services/web/src/pages/ProfilePage.tsx`.
///
/// Единственное место (кроме онбординга «Мои учреждения»), где можно сменить
/// текущее учреждение. Почта — только для чтения (В10 плана
/// `09-mobile-app.md`).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart' show Membership, MembershipStatus;
import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import 'change_password_form.dart';
import 'form_feedback.dart';
import 'institution_create_form.dart';

class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});

  @override
  ConsumerState<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends ConsumerState<ProfileScreen> {
  String? _switchingId;
  ApiError? _switchError;
  bool _loggingOut = false;

  Future<void> _switchInstitution(String institutionId) async {
    setState(() {
      _switchingId = institutionId;
      _switchError = null;
    });
    try {
      await ref.read(sessionProvider.notifier).selectInstitution(institutionId);
    } catch (error) {
      if (!mounted) return;
      setState(() => _switchError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _switchingId = null);
    }
  }

  Future<void> _logout() async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Выход',
      description: 'Выйти из аккаунта на этом устройстве?',
      confirmLabel: 'Выйти',
      danger: true,
    );
    if (confirmed != true || !mounted) return;

    setState(() => _loggingOut = true);
    try {
      // Локальный выход безусловен, ошибку сервера здесь не ловим —
      // редирект роутера сам уведёт на /login по смене статуса сессии.
      await ref.read(sessionProvider.notifier).logout();
    } finally {
      if (mounted) setState(() => _loggingOut = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final user = session.user;
    final institution = session.institution;
    final memberships = session.memberships;
    final membershipsError = session.membershipsError;

    return Scaffold(
      appBar: AppBar(title: const Text('Профиль')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          children: [
            Text('Почта', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            Text(user?.email ?? ''),
            const SizedBox(height: AppSpacing.xl),

            Text('Пароль', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            ChangePasswordForm(onSuccess: (_) => showSavedNotice(context, text: 'Пароль сохранён')),
            const SizedBox(height: AppSpacing.xl),

            Text('Мои учреждения', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            if (membershipsError != null)
              ScreenStateError(
                message: messageForError(membershipsError),
                onRetry: () => ref.read(sessionProvider.notifier).reloadMemberships(),
              ),
            if (membershipsError == null && memberships == null) const ScreenStateLoading(),
            if (membershipsError == null && memberships != null && memberships.isEmpty)
              const ScreenStateEmpty(message: 'Учреждений пока нет.'),
            if (membershipsError == null && memberships != null && memberships.isNotEmpty)
              for (final membership in memberships) _buildInstitutionCard(membership, institution?.id),
            if (_switchError != null) FormErrorText(messageForError(_switchError!)),
            const SizedBox(height: AppSpacing.xl),

            Text('Новое учреждение', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: AppSpacing.xs),
            // Новое учреждение текущим автоматически не становится — смена
            // происходит отдельной кнопкой «Сделать текущим» выше.
            InstitutionCreateForm(
              onCreated: (_) => ref.read(sessionProvider.notifier).reloadMemberships(),
            ),
            const SizedBox(height: AppSpacing.xl),

            OutlinedButton(
              onPressed: _loggingOut ? null : _logout,
              style: OutlinedButton.styleFrom(
                foregroundColor: AppColors.danger,
                side: const BorderSide(color: AppColors.danger),
              ),
              child: Text(_loggingOut ? 'Выходим…' : 'Выход'),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildInstitutionCard(Membership membership, String? currentInstitutionId) {
    final isCurrent = membership.institutionId == currentInstitutionId;
    final canSwitch = membership.status == MembershipStatus.active && !isCurrent;
    final busy = _switchingId == membership.institutionId;
    return Card(
      child: ListTile(
        title: Text(isCurrent ? '${membership.name} · текущее' : membership.name),
        subtitle: Text(
          '${kindLabels[membership.kind]} · ${roleLabels[membership.role]} · ${statusLabels[membership.status]}',
        ),
        trailing: canSwitch
            ? OutlinedButton(
                onPressed: (_switchingId != null) ? null : () => _switchInstitution(membership.institutionId),
                child: Text(busy ? 'Переключаем…' : 'Сделать текущим'),
              )
            : null,
      ),
    );
  }
}
