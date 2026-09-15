/// Мои учреждения — `/institutions`, он же онбординг. Зеркало
/// `services/web/src/pages/InstitutionsPage.tsx`.
///
/// Если учреждение уже выбрано (автовыбор по единственному или последнему
/// активному членству — забота `SessionNotifier`), роутер сюда не приводит.
/// Иначе два случая: активных членств нет — пусто и форма создания
/// учреждения; активных несколько — список с кнопкой «Выбрать». Ссылка «Есть
/// приглашение» — мобильное дополнение (веб её не показывает: там ссылка на
/// приглашение приходит сама, а на телефоне её вставляют вручную, раздел 3
/// плана `09-mobile-app.md`).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show Membership, MembershipStatus;
import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../router/app_router.dart';
import '../../ui/design_tokens.dart';
import '../../ui/screen_state.dart';
import 'form_feedback.dart';
import 'institution_create_form.dart';

class InstitutionsScreen extends ConsumerStatefulWidget {
  const InstitutionsScreen({super.key});

  @override
  ConsumerState<InstitutionsScreen> createState() => _InstitutionsScreenState();
}

class _InstitutionsScreenState extends ConsumerState<InstitutionsScreen> {
  String? _selectingId;
  ApiError? _selectError;

  Future<void> _goTo(String institutionId) async {
    setState(() {
      _selectingId = institutionId;
      _selectError = null;
    });
    try {
      await ref.read(sessionProvider.notifier).selectInstitution(institutionId);
      if (mounted) context.go('/');
    } catch (error) {
      if (!mounted) return;
      setState(() => _selectError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _selectingId = null);
    }
  }

  /// Нового учреждения ещё нет в списке членств сессии: без перечитывания
  /// `selectInstitution` не найдёт членство, контекст останется пустым, и
  /// роутер вернёт на онбординг. Перечитывание само запускает автовыбор
  /// единственного активного членства; явный выбор — на случай нескольких.
  Future<void> _onCreated(String institutionId) async {
    await ref.read(sessionProvider.notifier).reloadMemberships();
    if (!mounted) return;
    await _goTo(institutionId);
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final memberships = session.memberships;
    final membershipsError = session.membershipsError;
    final active = memberships?.where((m) => m.status == MembershipStatus.active).toList();

    return Scaffold(
      appBar: AppBar(title: const Text('Мои учреждения')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (membershipsError != null)
                ScreenStateError(
                  message: messageForError(membershipsError),
                  onRetry: () => ref.read(sessionProvider.notifier).reloadMemberships(),
                ),
              if (membershipsError == null && active == null) const ScreenStateLoading(),
              if (membershipsError == null && active != null && active.isEmpty) ...[
                const ScreenStateEmpty(
                  message: 'Создайте учреждение или откройте ссылку-приглашение от школы.',
                ),
                const SizedBox(height: AppSpacing.md),
                InstitutionCreateForm(onCreated: _onCreated),
              ],
              if (membershipsError == null && active != null && active.isNotEmpty)
                for (final membership in active) _buildInstitutionCard(membership),
              if (_selectError != null) FormErrorText(messageForError(_selectError!)),
              const SizedBox(height: AppSpacing.lg),
              TextButton(
                onPressed: () => context.go(invitePath),
                child: const Text('Есть приглашение'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildInstitutionCard(Membership membership) {
    final busy = _selectingId == membership.institutionId;
    return Card(
      child: ListTile(
        title: Text(membership.name),
        subtitle: Text('${kindLabels[membership.kind]} · ${roleLabels[membership.role]}'),
        trailing: OutlinedButton(
          onPressed: (_selectingId != null) ? null : () => _goTo(membership.institutionId),
          child: Text(busy ? 'Выбираем…' : 'Выбрать'),
        ),
      ),
    );
  }
}
