/// Форма смены пароля — общая для `/password` (принудительная смена
/// временного пароля) и Профиля (смена пароля по желанию), зеркало
/// `services/web/src/components/ChangePasswordForm.tsx`.
///
/// Что делать после успеха, решает вызывающий экран через [onSuccess]:
/// `/password` уходит на главную, Профиль остаётся на месте и показывает
/// «Сохранено».
///
/// Смена пароля гасит все refresh-сессии пользователя на сервере (план
/// `10-refresh.md`, вопрос 5) — текущий access ещё доживёт до истечения, но
/// следующий refresh получит `REFRESH_TOKEN_INVALID`. Поэтому сразу после
/// успешной смены форма сама входит заново новым паролем, как и веб (Ч4).
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../api/auth_api.dart';
import '../../api/errors.dart';
import '../../auth/session.dart';
import '../../i18n/error_messages.dart';
import '../../ui/design_tokens.dart';
import 'form_feedback.dart';

const String _mismatchMessage = 'Пароли не совпадают.';

class ChangePasswordForm extends ConsumerStatefulWidget {
  const ChangePasswordForm({super.key, required this.onSuccess, this.submitLabel = 'Сохранить пароль'});

  final void Function(User user) onSuccess;
  final String submitLabel;

  @override
  ConsumerState<ChangePasswordForm> createState() => _ChangePasswordFormState();
}

class _ChangePasswordFormState extends ConsumerState<ChangePasswordForm> {
  final _passwordController = TextEditingController();
  final _confirmController = TextEditingController();
  bool _pending = false;
  bool _mismatch = false;
  ApiError? _error;

  @override
  void dispose() {
    _passwordController.dispose();
    _confirmController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (_passwordController.text != _confirmController.text) {
      setState(() {
        _mismatch = true;
        _error = null;
      });
      return;
    }
    setState(() {
      _mismatch = false;
      _pending = true;
      _error = null;
    });
    try {
      final client = ref.read(apiClientProvider);
      final newPassword = _passwordController.text;
      final updated = await changePassword(client, newPassword);
      if (!mounted) return;
      try {
        // Сервер уже погасил все сессии — входим заново тем же паролем,
        // который только что отправили, чтобы получить свежую пару токенов.
        await ref.read(sessionProvider.notifier).login(updated.email, newPassword);
      } catch (loginError) {
        // Пароль сменился на сервере, но новая сессия не поднялась.
        // Оставлять пользователя с погашенной сессией нельзя — локальный
        // выход, как в вебе (К4, ревью `10-refresh.md`); `onSuccess` не
        // вызывается — сценарий смены пароля не завершился успехом.
        await ref.read(sessionProvider.notifier).logout();
        if (!mounted) return;
        setState(() => _error = loginError is ApiError ? loginError : const ApiError(0, unknownError));
        return;
      }
      if (!mounted) return;
      _passwordController.clear();
      _confirmController.clear();
      widget.onSuccess(updated);
    } catch (error) {
      if (!mounted) return;
      setState(() => _error = error is ApiError ? error : const ApiError(0, unknownError));
    } finally {
      if (mounted) setState(() => _pending = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        TextField(
          controller: _passwordController,
          obscureText: true,
          enabled: !_pending,
          autofillHints: const [AutofillHints.newPassword],
          decoration: const InputDecoration(labelText: 'Новый пароль'),
        ),
        const SizedBox(height: AppSpacing.sm),
        TextField(
          controller: _confirmController,
          obscureText: true,
          enabled: !_pending,
          autofillHints: const [AutofillHints.newPassword],
          decoration: const InputDecoration(labelText: 'Повтор пароля'),
        ),
        FieldErrorText(_mismatch ? _mismatchMessage : null),
        FormErrorText(_error == null ? null : messageForError(_error!)),
        const SizedBox(height: AppSpacing.sm),
        OutlinedButton(
          onPressed: _pending ? null : _submit,
          child: Text(_pending ? 'Сохраняем…' : widget.submitLabel),
        ),
      ],
    );
  }
}
