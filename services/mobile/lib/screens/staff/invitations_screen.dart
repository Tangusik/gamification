/// Приглашения одного учреждения — зеркало
/// `services/web/src/pages/InvitationsPage.tsx`: список, создание, отзыв,
/// копирование ссылки.
///
/// `institution_admin` видит все приглашения учреждения, `teacher` — только
/// свои: список фильтрует сервер, клиент ничего не урезает
/// ([invitationsProvider]).
///
/// Ссылка приглашения собирается на клиенте от origin `API_BASE_URL`:
/// `<origin>/invite#<token>` — вечный контракт напечатанного QR, менять
/// формат после origin нельзя
/// (`.claude/knowledge/gamification-service/03-invitations.md`, F6). Сам QR
/// веб рисует библиотекой; без новой зависимости на мобильном его не
/// нарисовать — здесь только текстовая ссылка с копированием в буфер.
/// Токен приглашения нигде не логируется.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show Clipboard, ClipboardData;
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/errors.dart';
import '../../api/institution_admin_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../ui/confirm_dialog.dart';
import '../../ui/design_tokens.dart';
import '../../ui/saved_notice.dart';
import '../../ui/screen_state.dart';
import '../common/form_feedback.dart';
import 'invitations_link.dart';
import 'invitations_providers.dart';

String? _invitationLink(String token) => buildInviteLink(inviteApiBaseUrl, token);

/// `дд.мм.гггг чч:мм` — как `toLocaleString('ru-RU')` веба.
String _formatDateTime(DateTime value) {
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}.${two(local.month)}.${local.year} ${two(local.hour)}:${two(local.minute)}';
}

class InvitationsScreen extends ConsumerStatefulWidget {
  const InvitationsScreen({super.key});

  @override
  ConsumerState<InvitationsScreen> createState() => _InvitationsScreenState();
}

class _InvitationsScreenState extends ConsumerState<InvitationsScreen> {
  final _maxUsesController = TextEditingController(text: '1');
  bool _creating = false;
  ApiError? _createError;

  String? _revokingId;
  ApiError? _revokeError;

  @override
  void dispose() {
    _maxUsesController.dispose();
    super.dispose();
  }

  Future<void> _handleCreate() async {
    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    final maxUses = int.tryParse(_maxUsesController.text) ?? 1;
    setState(() {
      _creating = true;
      _createError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await createInvitation(client, institution.id, maxUses);
      _maxUsesController.text = '1';
      ref.invalidate(invitationsProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _createError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _creating = false);
    }
  }

  Future<void> _handleRevoke(InvitationRead invitation) async {
    final confirmed = await showConfirmDialog(
      context,
      title: 'Отозвать приглашение?',
      description: 'Ссылка и напечатанный QR перестанут работать.',
      confirmLabel: 'Отозвать',
      danger: true,
    );
    if (confirmed != true || !mounted) return;

    final institution = ref.read(sessionProvider).institution;
    if (institution == null) return;
    setState(() {
      _revokingId = invitation.id;
      _revokeError = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      await revokeInvitation(client, institution.id, invitation.id);
      if (!mounted) return;
      ref.invalidate(invitationsProvider);
    } catch (error) {
      if (!mounted) return;
      setState(() => _revokeError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _revokingId = null);
    }
  }

  Future<void> _handleCopy(String link) async {
    await Clipboard.setData(ClipboardData(text: link));
    if (!mounted) return;
    showSavedNotice(context, text: 'Ссылка скопирована');
  }

  @override
  Widget build(BuildContext context) {
    final invitationsAsync = ref.watch(invitationsProvider);

    return Scaffold(
      appBar: AppBar(title: Text('Приглашения', style: Theme.of(context).textTheme.titleMedium)),
      body: RefreshIndicator(
        onRefresh: () async {
          try {
            final _ = await ref.refresh(invitationsProvider.future);
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
                      controller: _maxUsesController,
                      enabled: !_creating,
                      keyboardType: TextInputType.number,
                      decoration: const InputDecoration(labelText: 'Число применений'),
                    ),
                    FormErrorText(_createError == null ? null : messageForError(_createError!)),
                    const SizedBox(height: AppSpacing.sm),
                    OutlinedButton(
                      onPressed: _creating ? null : _handleCreate,
                      child: Text(_creating ? 'Создаём…' : 'Создать ссылку'),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            invitationsAsync.when(
              loading: () => const ScreenStateLoading(),
              error: (error, _) {
                if (error is ApiError && error.status == 403) return const ScreenStateForbidden();
                return ScreenStateError(
                  message: messageForError(error),
                  code: error is ApiError ? error.code : null,
                  onRetry: () => ref.invalidate(invitationsProvider),
                );
              },
              data: (invitations) {
                if (invitations.isEmpty) {
                  return const ScreenStateEmpty(message: 'Приглашений пока нет.');
                }
                return Column(
                  children: [
                    for (final invitation in invitations)
                      _InvitationCard(
                        invitation: invitation,
                        busy: _revokingId == invitation.id,
                        onCopy: _handleCopy,
                        onRevoke: () => _handleRevoke(invitation),
                      ),
                  ],
                );
              },
            ),
            FormErrorText(_revokeError == null ? null : messageForError(_revokeError!)),
          ],
        ),
      ),
    );
  }
}

class _InvitationCard extends StatelessWidget {
  const _InvitationCard({
    required this.invitation,
    required this.busy,
    required this.onCopy,
    required this.onRevoke,
  });

  final InvitationRead invitation;
  final bool busy;
  final void Function(String link) onCopy;
  final VoidCallback onRevoke;

  @override
  Widget build(BuildContext context) {
    final revoked = invitation.revokedAt != null;
    final link = _invitationLink(invitation.token);

    return Card(
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(
              link ?? 'Адрес приглашения не настроен (API_BASE_URL)',
              style: revoked
                  ? const TextStyle(decoration: TextDecoration.lineThrough, color: AppColors.textMuted)
                  : link == null
                      ? const TextStyle(color: AppColors.textMuted)
                      : null,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'Применений: ${invitation.usesCount}/${invitation.maxUses} · создано '
              '${_formatDateTime(invitation.createdAt)}${revoked ? ' · отозвано' : ''}',
              style: const TextStyle(color: AppColors.textMuted, fontSize: 12),
            ),
            if (!revoked) ...[
              const SizedBox(height: AppSpacing.sm),
              Row(
                children: [
                  if (link != null)
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () => onCopy(link),
                        child: const Text('Скопировать ссылку'),
                      ),
                    ),
                  if (link != null) const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: OutlinedButton(
                      onPressed: busy ? null : onRevoke,
                      style: OutlinedButton.styleFrom(
                        foregroundColor: AppColors.danger,
                        side: const BorderSide(color: AppColors.danger),
                      ),
                      child: Text(busy ? 'Отзываем…' : 'Отозвать'),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
