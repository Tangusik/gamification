/// Сумма валюты со спрайтом монеты, разбиением разрядов по `ru-RU`
/// («1 240») и знаком «−» на списании — перенос
/// `services/web/src/components/Money.tsx`.
///
/// Название валюты компонент не выводит: суммы остаются безымянными, слово
/// добавляет вызывающий экран рядом с компонентом (как в вебе).
library;

import 'package:flutter/material.dart';

import 'design_tokens.dart';
import 'pixel_sprite.dart';

/// Разбивка целого числа по разрядам через ` ` — так же, как
/// `toLocaleString('ru-RU')` в браузере. Без зависимости `intl`, которая не
/// входит в набор Ч4.
String _formatThousands(int value) {
  final digits = value.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(' ');
    buffer.write(digits[i]);
  }
  return buffer.toString();
}

class Money extends StatelessWidget {
  const Money({super.key, required this.amount, this.showPlus = false, this.size = 16});

  final int amount;

  /// Показать «+» перед положительной суммой (начисления в ленте операций).
  /// Отрицательная сумма всегда со знаком «−».
  final bool showPlus;

  final double size;

  @override
  Widget build(BuildContext context) {
    final isNegative = amount < 0;
    final formatted = _formatThousands(amount.abs());
    final sign = isNegative ? '−' : (showPlus ? '+' : '');
    final color = isNegative ? AppColors.danger : DefaultTextStyle.of(context).style.color;

    return Row(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.baseline,
      textBaseline: TextBaseline.alphabetic,
      children: [
        PixelSprite(name: SpriteName.coin, size: size),
        const SizedBox(width: AppSpacing.xs),
        Text('$sign$formatted', style: TextStyle(color: color)),
      ],
    );
  }
}
