import 'package:flutter/material.dart';

abstract final class WainakTokens {
  static const background = Color(0xFFFFF9F5);
  static const ink = Color(0xFF2B2528);
  static const muted = Color(0xFF6B5F65);
  static const primary = Color(0xFF6F304A);
  static const outline = Color(0xFF8C747F);
  static const success = Color(0xFF23544D);
  static const danger = Color(0xFF9E313D);
  static const target = 48.0;
  static const spacing = 16.0;

  static ThemeData theme(Brightness brightness) {
    final dark = brightness == Brightness.dark;
    final scheme =
        ColorScheme.fromSeed(
          seedColor: primary,
          brightness: brightness,
        ).copyWith(
          primary: dark ? const Color(0xFFE4A6BE) : primary,
          onPrimary: dark ? const Color(0xFF2F1421) : Colors.white,
          surface: dark ? const Color(0xFF2D242B) : Colors.white,
          onSurface: dark ? const Color(0xFFF4EAF0) : ink,
          onSurfaceVariant: dark ? const Color(0xFFCABAC4) : muted,
          outline: dark ? const Color(0xFFB29BA9) : outline,
          error: dark ? const Color(0xFFFFB2BF) : danger,
          onError: dark ? const Color(0xFF4D101D) : Colors.white,
        );
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      brightness: brightness,
      fontFamily: 'NotoSansArabic',
    );
    final text = base.textTheme
        .copyWith(
          headlineMedium: TextStyle(
            fontSize: 28,
            height: 1.5,
            fontWeight: FontWeight.w600,
            color: scheme.onSurface,
          ),
          titleLarge: TextStyle(
            fontSize: 24,
            height: 1.5,
            fontWeight: FontWeight.w600,
            color: scheme.onSurface,
          ),
          titleMedium: TextStyle(
            fontSize: 18,
            height: 1.6,
            fontWeight: FontWeight.w600,
            color: scheme.onSurface,
          ),
          bodyLarge: TextStyle(
            fontSize: 18,
            height: 1.7,
            color: scheme.onSurface,
          ),
          bodyMedium: TextStyle(
            fontSize: 16,
            height: 1.7,
            color: scheme.onSurface,
          ),
          bodySmall: TextStyle(
            fontSize: 16,
            height: 1.7,
            color: scheme.onSurfaceVariant,
          ),
          labelLarge: const TextStyle(
            fontSize: 16,
            height: 1.5,
            fontWeight: FontWeight.w600,
          ),
        )
        .apply(fontFamily: 'NotoSansArabic');
    final shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(12),
    );
    return base.copyWith(
      scaffoldBackgroundColor: dark ? const Color(0xFF211A20) : background,
      textTheme: text,
      materialTapTargetSize: MaterialTapTargetSize.padded,
      visualDensity: VisualDensity.standard,
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(target, target),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape: shape,
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(target, target),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          side: BorderSide(color: scheme.outline),
          shape: shape,
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(target, target)),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(target, target)),
      ),
      inputDecorationTheme: InputDecorationTheme(
        contentPadding: const EdgeInsets.all(16),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: scheme.outline),
        ),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: scheme.surface,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: dark ? const Color(0xFF211A20) : background,
        foregroundColor: scheme.onSurface,
        scrolledUnderElevation: 0,
      ),
    );
  }
}
