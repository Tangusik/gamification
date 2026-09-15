/// Пиксельный спрайт 8×8 из дизайна «1c Контрастный» (Nocturne).
///
/// Карты пикселей и золотая палитра монеты перенесены буквально из
/// `services/web/src/components/PixelSprite.tsx`. Там рисуется через SVG
/// `<rect>`, здесь — эквивалент через `CustomPainter`: без внешних файлов.
///
/// Спрайт декоративный: рядом всегда есть текстовая подпись, поэтому виджет
/// не даёт `Semantics`-имени (аналог `aria-hidden` веба).
library;

import 'package:flutter/material.dart';

enum SpriteName { coin, star, heart, bolt, trophy, chest, check, qr, house, user, cam }

/// Карта 8×8: `.` — пусто, остальные символы — закрашенный пиксель.
const Map<SpriteName, List<String>> _maps = {
  SpriteName.coin: ['..####..', '.#GGGG#.', '#GGLLGG#', '#GLGGLG#', '#GLGGLG#', '#GGLLGG#', '.#GGGG#.', '..####..'],
  SpriteName.star: ['...##...', '...##...', '.######.', '..####..', '..####..', '.##..##.', '##....##', '........'],
  SpriteName.heart: ['.##..##.', '########', '########', '########', '.######.', '..####..', '...##...', '........'],
  SpriteName.bolt: ['....##..', '...###..', '..###...', '.#####..', '..####..', '...##...', '..##....', '.#......'],
  SpriteName.trophy: ['########', '#.####.#', '#.####.#', '.######.', '..####..', '...##...', '..####..', '.######.'],
  SpriteName.chest: ['.######.', '#......#', '########', '##.##.##', '#..##..#', '#......#', '########', '........'],
  SpriteName.check: ['........', '......##', '.....##.', '....##..', '##.##...', '###.....', '.#......', '........'],
  SpriteName.qr: ['###.#.##', '#.#.#.#.', '###..###', '...#....', '#.##.#.#', '###..###', '#.#.#..#', '###.####'],
  SpriteName.house: ['...##...', '..####..', '.######.', '########', '.#....#.', '.#.##.#.', '.#.##.#.', '.######.'],
  SpriteName.user: ['..####..', '.######.', '.######.', '..####..', '........', '.######.', '########', '########'],
  SpriteName.cam: ['..#..#..', '########', '#......#', '#..##..#', '#.#..#.#', '#..##..#', '#......#', '########'],
};

/// Золотая палитра монеты — используется по умолчанию, пока цвет не
/// переопределён параметром `color`.
const Map<String, Color> _coinTones = {
  '#': Color(0xFF7A5A00),
  'G': Color(0xFFFFC31A),
  'L': Color(0xFFFFF0A8),
};

class PixelSprite extends StatelessWidget {
  const PixelSprite({super.key, required this.name, this.size = 16, this.color});

  final SpriteName name;

  /// Сторона квадрата в логических px. По умолчанию 16 — как в дизайне
  /// для меню и подписей.
  final double size;

  /// Цвет заливки. По умолчанию `currentColor` веба нет аналога в Flutter,
  /// поэтому null трактуется как цвет текста темы, кроме монеты: она без
  /// переопределения рисуется золотой палитрой дизайна.
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final effectiveColor = color ?? DefaultTextStyle.of(context).style.color ?? AppColorsFallback.text;
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(
        painter: _PixelSpritePainter(name: name, color: color, fallbackColor: effectiveColor),
      ),
    );
  }
}

/// Фолбэк-цвет, если тема недоступна (например, в изолированном тесте).
abstract final class AppColorsFallback {
  static const text = Color(0xFFF0F0FF);
}

class _PixelSpritePainter extends CustomPainter {
  _PixelSpritePainter({required this.name, required this.color, required this.fallbackColor});

  final SpriteName name;
  final Color? color;
  final Color fallbackColor;

  @override
  void paint(Canvas canvas, Size size) {
    final rows = _maps[name]!;
    final cell = size.width / 8;
    final useCoinTones = name == SpriteName.coin && color == null;
    final paint = Paint()..style = PaintingStyle.fill;

    for (var y = 0; y < rows.length; y++) {
      final row = rows[y];
      for (var x = 0; x < row.length; x++) {
        final ch = row[x];
        if (ch == '.') continue;
        paint.color = useCoinTones ? (_coinTones[ch] ?? fallbackColor) : fallbackColor;
        canvas.drawRect(Rect.fromLTWH(x * cell, y * cell, cell, cell), paint);
      }
    }
  }

  @override
  bool shouldRepaint(covariant _PixelSpritePainter oldDelegate) =>
      oldDelegate.name != name || oldDelegate.color != color || oldDelegate.fallbackColor != fallbackColor;
}
