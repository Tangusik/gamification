/// Экран регистрации — `/register`, зеркало
/// `services/web/src/pages/RegisterPage.tsx`. Регистрация сама не выдаёт
/// токен — `SessionNotifier.register` сразу входит тем же паролем.
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

class RegisterScreen extends ConsumerStatefulWidget {
  const RegisterScreen({super.key});

  @override
  ConsumerState<RegisterScreen> createState() => _RegisterScreenState();
}

class _RegisterScreenState extends ConsumerState<RegisterScreen> {
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  bool _pending = false;
  ApiError? _error;

  @override
  void dispose() {
    _emailController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  /// Сюда ведёт и неавторизованный переход по ссылке-приглашению — тогда
  /// `?from=` начинается с пути приёма приглашения (`InviteScreen._goAuth`).
  bool get _fromInvite {
    final from = GoRouterState.of(context).uri.queryParameters['from'];
    return from != null && from.startsWith(invitePath);
  }

  Future<void> _submit() async {
    setState(() {
      _pending = true;
      _error = null;
    });
    try {
      await ref.read(sessionProvider.notifier).register(_emailController.text, _passwordController.text);
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
      appBar: AppBar(title: const Text('Регистрация')),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (_fromInvite) ...[
                Semantics(
                  liveRegion: true,
                  child: const Text('После регистрации приглашение будет принято автоматически.'),
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
                autofillHints: const [AutofillHints.newPassword],
                decoration: const InputDecoration(labelText: 'Пароль'),
              ),
              FieldErrorText(fieldErrors?['password']),
              FormErrorText(_error == null ? null : messageForError(_error!)),
              const SizedBox(height: AppSpacing.md),
              OutlinedButton(
                onPressed: _pending ? null : _submit,
                child: Text(_pending ? 'Создаём…' : 'Зарегистрироваться'),
              ),
              const SizedBox(height: AppSpacing.lg),
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Text('Уже есть учётная запись?'),
                  TextButton(onPressed: () => context.go(loginPath), child: const Text('Войти')),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
