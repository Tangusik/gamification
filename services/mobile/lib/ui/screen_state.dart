/// Общий виджет трёх состояний экрана: загрузка, ошибка, пустота — перенос
/// `services/web/src/components/ScreenState.tsx`. Разбор `ApiError` и
/// текстов ошибок делает Ч2 (`lib/api`, `lib/i18n`), здесь — только отрисовка
/// готового текста и колбэка «Повторить».
library;

import 'package:flutter/material.dart';

import 'design_tokens.dart';

class ScreenStateLoading extends StatelessWidget {
  const ScreenStateLoading({super.key});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xl),
      child: Center(
        child: Semantics(
          liveRegion: true,
          label: 'Загрузка…',
          child: const SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2, color: AppColors.accent),
          ),
        ),
      ),
    );
  }
}

class ScreenStateError extends StatelessWidget {
  const ScreenStateError({super.key, required this.message, required this.onRetry, this.code});

  /// Готовый текст ошибки (перевод кода делает вызывающий экран).
  final String message;

  /// Код ошибки для мелкой подписи рядом с текстом — как `screen-state-code` веба.
  final String? code;

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text.rich(
              TextSpan(
                style: const TextStyle(color: AppColors.textMuted, fontFamily: AppFonts.body),
                children: [
                  TextSpan(text: message),
                  if (code != null)
                    TextSpan(
                      text: ' ($code)',
                      style: const TextStyle(color: AppColors.textFaint, fontSize: 12),
                    ),
                ],
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            OutlinedButton(onPressed: onRetry, child: const Text('Повторить')),
          ],
        ),
      ),
    );
  }
}

class ScreenStateForbidden extends StatelessWidget {
  const ScreenStateForbidden({super.key});

  @override
  Widget build(BuildContext context) {
    return Semantics(
      liveRegion: true,
      child: const Padding(
        padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('Нет доступа', style: TextStyle(color: AppColors.text, fontWeight: FontWeight.w600)),
            SizedBox(height: AppSpacing.xs),
            Text('Недостаточно прав для этого действия.', style: TextStyle(color: AppColors.textMuted)),
          ],
        ),
      ),
    );
  }
}

class ScreenStateEmpty extends StatelessWidget {
  const ScreenStateEmpty({super.key, required this.message, this.action});

  final String message;

  /// Действие рядом с пустым состоянием, например кнопка «Создать».
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(message, style: const TextStyle(color: AppColors.textMuted)),
          if (action != null) ...[const SizedBox(height: AppSpacing.sm), action!],
        ],
      ),
    );
  }
}
