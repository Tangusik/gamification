/// Демо-экран виджетов дизайн-системы 1c — временная витрина до экранов Ч5
/// (готовность Ч4: «демо-экран виджетов на эмуляторе, кириллица в Press
/// Start 2P читается»). Заменяет собой стартовый счётчик шаблона Flutter.
library;

import 'package:flutter/material.dart';

import 'confirm_dialog.dart';
import 'design_tokens.dart';
import 'money.dart';
import 'pixel_sprite.dart';
import 'saved_notice.dart';
import 'screen_state.dart';

class DemoScreen extends StatefulWidget {
  const DemoScreen({super.key});

  @override
  State<DemoScreen> createState() => _DemoScreenState();
}

enum _DemoState { loading, error, empty, ready }

class _DemoScreenState extends State<DemoScreen> {
  _DemoState _state = _DemoState.ready;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Gamification', style: TextStyle(fontFamily: AppFonts.pixel, fontSize: 16)),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Баланс', style: TextStyle(fontFamily: AppFonts.pixel, fontSize: 14)),
            const SizedBox(height: AppSpacing.sm),
            const Money(amount: 1240),
            const SizedBox(height: AppSpacing.xs),
            const Money(amount: -85, showPlus: false),
            const SizedBox(height: AppSpacing.xs),
            const Money(amount: 50, showPlus: true),
            const SizedBox(height: AppSpacing.xl),

            const Text('Спрайты', style: TextStyle(fontFamily: AppFonts.pixel, fontSize: 14)),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.md,
              runSpacing: AppSpacing.md,
              children: SpriteName.values
                  .map((name) => PixelSprite(name: name, size: 24, color: AppColors.text))
                  .toList(),
            ),
            const SizedBox(height: AppSpacing.xl),

            const Text('Состояние экрана', style: TextStyle(fontFamily: AppFonts.pixel, fontSize: 14)),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                OutlinedButton(
                  onPressed: () => setState(() => _state = _DemoState.loading),
                  child: const Text('Загрузка'),
                ),
                OutlinedButton(
                  onPressed: () => setState(() => _state = _DemoState.error),
                  child: const Text('Ошибка'),
                ),
                OutlinedButton(
                  onPressed: () => setState(() => _state = _DemoState.empty),
                  child: const Text('Пусто'),
                ),
              ],
            ),
            _buildDemoState(),
            const SizedBox(height: AppSpacing.xl),

            const Text('Действия', style: TextStyle(fontFamily: AppFonts.pixel, fontSize: 14)),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              children: [
                OutlinedButton(
                  onPressed: () async {
                    final confirmed = await showConfirmDialog(
                      context,
                      title: 'Удалить привилегию',
                      description: 'Действие нельзя отменить.',
                      confirmLabel: 'Удалить',
                      danger: true,
                    );
                    if (confirmed == true && context.mounted) {
                      showSavedNotice(context);
                    }
                  },
                  child: const Text('Диалог подтверждения'),
                ),
                OutlinedButton(
                  onPressed: () => showSavedNotice(context),
                  child: const Text('Показать «Сохранено»'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildDemoState() {
    switch (_state) {
      case _DemoState.loading:
        return const ScreenStateLoading();
      case _DemoState.error:
        return ScreenStateError(
          message: 'Не удалось загрузить данные',
          code: 'NETWORK_ERROR',
          onRetry: () => setState(() => _state = _DemoState.ready),
        );
      case _DemoState.empty:
        return ScreenStateEmpty(
          message: 'Пока пусто',
          action: OutlinedButton(
            onPressed: () => setState(() => _state = _DemoState.ready),
            child: const Text('Добавить'),
          ),
        );
      case _DemoState.ready:
        return const Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
          child: Text('Готово', style: TextStyle(color: AppColors.textMuted)),
        );
    }
  }
}
