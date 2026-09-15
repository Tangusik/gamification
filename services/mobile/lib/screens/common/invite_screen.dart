/// Приём приглашения — `/invite`, зеркало
/// `services/web/src/pages/InvitePage.tsx`, вопрос 9 плана `09-mobile-app.md`
/// (А: поле «вставьте ссылку-приглашение», без QR и App Links).
///
/// В отличие от веба токен приходит не из `location.hash` самого приложения
/// (мобильному нечем поймать открытую в браузере ссылку без App Links —
/// раздел 9 плана), а из текста, который пользователь вставляет в поле. Разбор
/// ссылки — чистая функция [parseInviteToken].
///
/// Экран доступен и анониму (`app_router.dart` исключает `/invite` из
/// проверки на вход). Если пользователь ещё не вошёл, принять приглашение
/// нельзя — экран предлагает войти или зарегистрироваться и кладёт
/// вставленную ссылку в [pendingInviteProvider] (память процесса, не диск и
/// не URL — находка С1 ревью безопасности, `09-mobile-app.md`, Ч6): после
/// входа `_redirect` вернёт сюда же по `?from=/invite`, экран заберёт ссылку
/// из провайдера, тут же очистит его и запустит приём сам, без повторного
/// нажатия. Автоприём срабатывает только из этого состояния в памяти — сам по
/// себе переход на `/invite` (в т.ч. из чужого intent) его не запускает.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/auth_api.dart' show Membership;
import '../../api/errors.dart';
import '../../api/institutions_api.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../i18n/labels.dart';
import '../../router/app_router.dart';
import '../../ui/design_tokens.dart';
import 'form_feedback.dart';
import 'invite_link.dart';
import 'pending_invite.dart';

class InviteScreen extends ConsumerStatefulWidget {
  const InviteScreen({super.key});

  @override
  ConsumerState<InviteScreen> createState() => _InviteScreenState();
}

class _InviteScreenState extends ConsumerState<InviteScreen> {
  late final TextEditingController _linkController;

  /// Автоприём запускается не более одного раза за жизнь экрана — иначе
  /// перестройка виджета после `setState` могла бы повторить запрос.
  bool _started = false;

  bool _pending = false;
  String? _fieldError;
  ApiError? _error;
  Membership? _accepted;

  bool _goingPending = false;
  ApiError? _goError;

  @override
  void initState() {
    super.initState();
    _linkController = TextEditingController();
  }

  @override
  void dispose() {
    _linkController.dispose();
    super.dispose();
  }

  void _goAuth(String targetPath) {
    final link = _linkController.text.trim();
    if (link.isNotEmpty) {
      ref.read(pendingInviteProvider.notifier).state = link;
    }
    final target = Uri(path: targetPath, queryParameters: {'from': invitePath});
    context.go(target.toString());
  }

  Future<void> _accept() async {
    final token = parseInviteToken(_linkController.text);
    if (token.isEmpty) {
      setState(() => _fieldError = 'Ссылка приглашения не содержит кода. Проверьте адрес.');
      return;
    }
    setState(() {
      _pending = true;
      _fieldError = null;
      _error = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final membership = await acceptInvitation(client, token);
      if (!mounted) return;
      setState(() {
        _accepted = membership;
        _pending = false;
      });

      final notifier = ref.read(sessionProvider.notifier);
      await notifier.reloadMemberships();
      if (!mounted) return;
      if (ref.read(sessionProvider).institution == null) {
        // Своего учреждения ещё не было — становимся участником принятого
        // сразу, без ожидания следующего автовыбора.
        try {
          await notifier.selectInstitution(membership.institutionId);
        } catch (_) {
          // Необязательная попытка: не получилось — можно нажать
          // «Перейти в учреждение» ниже.
        }
      }
    } catch (error) {
      if (!mounted) return;
      setState(() {
        _pending = false;
        _error = error is ApiError ? error : const ApiError(0, unknownError);
      });
    }
  }

  Future<void> _handleGo(String institutionId) async {
    setState(() {
      _goingPending = true;
      _goError = null;
    });
    try {
      await ref.read(sessionProvider.notifier).selectInstitution(institutionId);
      if (mounted) context.go('/');
    } catch (error) {
      if (!mounted) return;
      setState(() => _goError = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _goingPending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final session = ref.watch(sessionProvider);
    final isAnon = session.status == SessionStatus.anon;
    final isAuthed = session.status == SessionStatus.authed;

    // Автоприём — только из ссылки, которую сам пользователь вставил в этом
    // процессе и оставил в [pendingInviteProvider] перед уходом на вход или
    // регистрацию. Внешний переход на `/invite` (чужой intent, ручной ввод
    // маршрута) провайдер не трогает, поэтому автоприём не запускает.
    final pendingLink = ref.watch(pendingInviteProvider);
    if (!_started && isAuthed && pendingLink != null && pendingLink.isNotEmpty) {
      _started = true;
      _linkController.text = pendingLink;
      // Провайдер нельзя менять во время построения дерева — чистим его и
      // запускаем приём в колбэке после кадра. Повторное открытие `/invite`
      // уже не может сработать автоматически.
      WidgetsBinding.instance.addPostFrameCallback((_) {
        ref.read(pendingInviteProvider.notifier).state = null;
        _accept();
      });
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Приглашение')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: _accepted != null ? _buildDone(_accepted!) : _buildForm(isAnon, isAuthed),
        ),
      ),
    );
  }

  Widget _buildForm(bool isAnon, bool isAuthed) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        const Text('Вставьте ссылку-приглашение, которую прислало учреждение.'),
        const SizedBox(height: AppSpacing.md),
        TextField(
          controller: _linkController,
          enabled: !_pending,
          // Токен приглашения не должен попасть в словарь клавиатуры.
          autocorrect: false,
          enableSuggestions: false,
          decoration: const InputDecoration(labelText: 'Ссылка-приглашение'),
        ),
        FieldErrorText(_fieldError),
        const SizedBox(height: AppSpacing.md),
        if (isAnon) ...[
          const Text('Чтобы принять приглашение, войдите или зарегистрируйтесь.'),
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.sm,
            children: [
              OutlinedButton(onPressed: () => _goAuth(loginPath), child: const Text('Войти')),
              OutlinedButton(
                onPressed: () => _goAuth(registerPath),
                child: const Text('Зарегистрироваться'),
              ),
            ],
          ),
        ] else
          OutlinedButton(
            onPressed: (_pending || !isAuthed) ? null : _accept,
            child: Text(_pending ? 'Принимаем…' : 'Принять приглашение'),
          ),
        FormErrorText(_error == null ? null : messageForError(_error!)),
      ],
    );
  }

  Widget _buildDone(Membership membership) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text('Готово: вы участник учреждения «${membership.name}» в роли ${roleLabels[membership.role]}.'),
        const SizedBox(height: AppSpacing.md),
        OutlinedButton(
          onPressed: _goingPending ? null : () => _handleGo(membership.institutionId),
          child: Text(_goingPending ? 'Переходим…' : 'Перейти в учреждение'),
        ),
        FormErrorText(_goError == null ? null : messageForError(_goError!)),
      ],
    );
  }
}
