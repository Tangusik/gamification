/// Мелкие текстовые виджеты обратной связи форм — перенос
/// `services/web/src/components/FieldError.tsx` и `FormError.tsx`.
///
/// Общие для всех форм экрана — вход, регистрация, смена пароля, создание
/// учреждения, приём приглашения.
library;

import 'package:flutter/material.dart';

import '../../ui/design_tokens.dart';

/// Ошибка рядом с конкретным полем формы, например по коду 422.
class FieldErrorText extends StatelessWidget {
  const FieldErrorText(this.message, {super.key});

  final String? message;

  @override
  Widget build(BuildContext context) {
    if (message == null) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(top: AppSpacing.xs),
      child: Text(message!, style: const TextStyle(color: AppColors.danger, fontSize: 12)),
    );
  }
}

/// Ошибка формы целиком — общий код ответа сервера.
class FormErrorText extends StatelessWidget {
  const FormErrorText(this.message, {super.key});

  final String? message;

  @override
  Widget build(BuildContext context) {
    if (message == null) return const SizedBox.shrink();
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Text(message!, style: const TextStyle(color: AppColors.danger)),
      ),
    );
  }
}
