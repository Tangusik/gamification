/// Экран входа — `/login`, зеркало `services/web/src/pages/LoginPage.tsx`.
///
/// Дальнейшая навигация после успешного входа — забота `goRouterProvider`
/// (`_redirect`): как только сессия становится `authed`, роутер сам уводит
/// туда, откуда пришли (`?from=`), поэтому здесь нет явного `context.go`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../router/app_router.dart';
import '../../ui/design_tokens.dart';
import 'form_feedback.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _pending = false;
  ApiError? _error;
  String? _notice;
  bool _noticeConsumed = false;

  @override
  void initState() {
    super.initState();
    // `session.notice` («Сессия истекла…») показываем один раз и сразу
    // гасим в сессии — иначе он всплывёт снова при следующем открытии этого
    // экрана уже без повода.
    WidgetsBinding.instance.addPostFrameCallback((_) => _consumeNotice());
  }

  void _consumeNotice() {
    if (_noticeConsumed || !mounted) return;
    _noticeConsumed = true;
    final notice = ref.read(sessionProvider).notice;
    if (notice != null) {
      setState(() => _notice = notice);
      ref.read(sessionProvider.notifier).clearNotice();
    }
  }

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    setState(() {
      _pending = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider.notifier).login(_emailController.text, _passwordController.text);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _pending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final fieldErrors = _error?.fieldErrors;

    return Scaffold(
      appBar: AppBar(title: const Text('Вход')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_notice != null) ...[
                Semantics(
                  liveRegion: true,
                  child: Text(_notice!, style: const TextStyle(color: AppColors.info)),
                ),
                const SizedBox(height: AppSpacing.md),
              ],
              TextField(
                controller: _emailController,
                enabled: !_pending,
                keyboardType: TextInputType.emailAddress,
                autofillHints: const [AutofillHints.email],
                decoration: const InputDecoration(labelText: 'Почта'),
              ),
              FieldErrorText(fieldErrors?['email']),
              const SizedBox(height: AppSpacing.sm),
              TextField(
                controller: _passwordController,
                enabled: !_pending,
                obscureText: true,
                autofillHints: const [AutofillHints.password],
                decoration: const InputDecoration(labelText: 'Пароль'),
              ),
              FieldErrorText(fieldErrors?['password']),
              FormErrorText(_error == null ? null : messageForError(_error!)),
              const SizedBox(height: AppSpacing.md),
              OutlinedButton(
                onPressed: _pending ? null : _submit,
                child: Text(_pending ? 'Входим…' : 'Войти'),
              ),
              const SizedBox(height: AppSpacing.lg),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('Нет учётной записи?'),
                  TextButton(
                    onPressed: () => context.go(registerPath),
                    child: const Text('Зарегистрироваться'),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
