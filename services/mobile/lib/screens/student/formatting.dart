/// Форматирование чисел и дат для экранов ученика — вручную, без `intl`
/// (правило Ч5 плана `09-mobile-app.md`, тот же приём, что в `lib/ui/money.dart`).
library;

/// Разбивка целого числа по разрядам через пробел — как `toLocaleString('ru-RU')`.
String formatThousands(int value) {
  final digits = value.abs().toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(' ');
    buffer.write(digits[i]);
  }
  return (value < 0 ? '−' : '') + buffer.toString();
}

/// `дд.мм.гггг чч:мм` в локальном времени устройства — приближение
/// `toLocaleString('ru-RU')` веба без секунд, которые на телефоне не нужны.
String formatDateTime(DateTime value) {
  final local = value.toLocal();
  String two(int n) => n.toString().padLeft(2, '0');
  return '${two(local.day)}.${two(local.month)}.${local.year} ${two(local.hour)}:${two(local.minute)}';
}
