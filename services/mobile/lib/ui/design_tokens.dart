/// Токены дизайн-системы «1c Контрастный» (Nocturne), решение владельца В2.
///
/// Значения переносятся буквально из `services/web/src/index.css`
/// (`:root`) — источник токенов для всех платформ. Здесь собраны в одном
/// месте, чтобы не размножать хекс-коды и отступы по виджетам.
library;

import 'package:flutter/material.dart';

/// Цветовая палитра. Имена и значения — как в `--color-*` веба.
abstract final class AppColors {
  static const bg = Color(0xFF080811);
  static const surface = Color(0xFF11111F);
  static const border = Color(0xFF2A2A44);
  static const text = Color(0xFFF0F0FF);
  static const textMuted = Color(0xB3F0F0FF); // rgba(240,240,255,0.7)
  static const textFaint = Color(0x80F0F0FF); // rgba(240,240,255,0.5)

  static const accent = Color(0xFFBBAAFF);
  static const accentSoft = Color(0x1FBBAAFF); // rgba(187,170,255,0.12)
  static const accentSoftStrong = Color(0x38BBAAFF); // rgba(187,170,255,0.22)
  static const coin = Color(0xFFFFC31A);
  static const success = Color(0xFF5CE483);
  static const danger = Color(0xFFFF7A85);
  static const dangerSoft = Color(0x1FFF7A85); // rgba(255,122,133,0.12)
  static const dangerSoftStrong = Color(0x38FF7A85); // rgba(255,122,133,0.22)
  static const info = Color(0xFF4CC9FF);
}

/// Отступы — шаг 4 px, как в `rem`-сетке веба (0.25rem = 4px при 16px корне).
abstract final class AppSpacing {
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 24.0;
}

/// Радиусы скругления — `--radius-*` веба.
abstract final class AppRadius {
  static const sm = 4.0;
  static const md = 8.0;
  static const lg = 14.0;
}

/// Семейства шрифтов — `--font-body`/`--font-pixel` веба. Файлы лежат в
/// `assets/fonts/`, подключены через `pubspec.yaml`, из сети не грузятся.
abstract final class AppFonts {
  static const body = 'Inter';
  /// Только для заголовков и коротких подписей, размер 10–28 px.
  static const pixel = 'Press Start 2P';
}

/// Готовая `ThemeData` направления 1c: кнопки контурные (не заливка — иначе
/// светлый акцент на тёмном фоне проваливает контраст), фокус акцентным
/// цветом.
ThemeData buildAppTheme() {
  final colorScheme = const ColorScheme.dark(
    surface: AppColors.bg,
    onSurface: AppColors.text,
    primary: AppColors.accent,
    onPrimary: AppColors.bg,
    secondary: AppColors.coin,
    error: AppColors.danger,
    onError: AppColors.bg,
    outline: AppColors.border,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    scaffoldBackgroundColor: AppColors.bg,
    fontFamily: AppFonts.body,
    appBarTheme: const AppBarTheme(
      backgroundColor: AppColors.bg,
      foregroundColor: AppColors.text,
      elevation: 0,
      surfaceTintColor: Colors.transparent,
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: AppColors.surface,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        side: const BorderSide(color: AppColors.border),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: const BorderSide(color: AppColors.border),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: const BorderSide(color: AppColors.accent, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(AppRadius.md),
        borderSide: const BorderSide(color: AppColors.danger),
      ),
    ),
    // Контурный стиль — рамка и текст акцентным цветом, заливка прозрачная.
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: AppColors.accent,
        side: const BorderSide(color: AppColors.accent),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadius.md),
        ),
        padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.lg,
          vertical: AppSpacing.sm,
        ),
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(foregroundColor: AppColors.accent),
    ),
    snackBarTheme: const SnackBarThemeData(
      backgroundColor: AppColors.surface,
      contentTextStyle: TextStyle(color: AppColors.text),
      behavior: SnackBarBehavior.floating,
    ),
    focusColor: AppColors.accent,
    dividerColor: AppColors.border,
    textTheme: const TextTheme(
      headlineMedium: TextStyle(
        fontFamily: AppFonts.pixel,
        fontSize: 20,
        color: AppColors.text,
      ),
      titleMedium: TextStyle(
        fontFamily: AppFonts.pixel,
        fontSize: 14,
        color: AppColors.text,
      ),
      bodyMedium: TextStyle(
        fontFamily: AppFonts.body,
        color: AppColors.text,
      ),
    ),
  );
}
