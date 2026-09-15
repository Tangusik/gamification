import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/screens/common/invite_link.dart';

void main() {
  group('parseInviteToken', () {
    test('достаёт токен из фрагмента полной ссылки', () {
      expect(parseInviteToken('https://your-gamification.ru/invite#abc123'), 'abc123');
    });

    test('принимает голый токен без ссылки', () {
      expect(parseInviteToken('abc123'), 'abc123');
    });

    test('обрезает пробелы по краям вставленного текста', () {
      expect(parseInviteToken('  https://x/invite#abc123  '), 'abc123');
    });

    test('пустая строка даёт пустую строку', () {
      expect(parseInviteToken(''), '');
      expect(parseInviteToken('   '), '');
    });

    test('ссылка без фрагмента после # тоже даёт пустую строку', () {
      expect(parseInviteToken('https://your-gamification.ru/invite#'), '');
    });
  });
}
