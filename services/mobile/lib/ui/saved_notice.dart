/// Уведомление об успехе — перенос
/// `services/web/src/components/SavedNotice.tsx`. У веба уведомление рисуется
/// на месте, без ухода со страницы; в Flutter для этого нет DOM-аналога без
/// лишнего состояния, поэтому здесь — хелпер поверх `SnackBar` с той же
/// подписью и спрайтом.
library;

import 'package:flutter/material.dart';

import 'design_tokens.dart';
import 'pixel_sprite.dart';

void showSavedNotice(BuildContext context, {String text = 'Сохранено'}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(
      SnackBar(
        content: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            const PixelSprite(name: SpriteName.check, size: 14, color: AppColors.success),
            const SizedBox(width: AppSpacing.xs),
            Text(text, style: const TextStyle(color: AppColors.success)),
          ],
        ),
        backgroundColor: AppColors.surface,
        duration: const Duration(seconds: 3),
      ),
    );
}
