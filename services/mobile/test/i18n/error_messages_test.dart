import 'package:flutter_test/flutter_test.dart';
import 'package:gamification_mobile/api/errors.dart';
import 'package:gamification_mobile/i18n/error_messages.dart';

void main() {
  test('известный код даёт человеческий текст', () {
    expect(messageForCode('INSUFFICIENT_BALANCE'), 'Недостаточно средств на балансе.');
  });

  test('незнакомый код возвращает запасной текст с самим кодом', () {
    expect(messageForCode('SOME_NEW_CODE'), contains('SOME_NEW_CODE'));
  });

  test('коды преподавателей, учеников и групп (09b) покрыты текстом', () {
    expect(messageForCode('MEMBER_NOT_FOUND'), 'Участник не найден.');
    expect(messageForCode('GROUP_NOT_FOUND'), 'Группа не найдена.');
    expect(messageForCode('GROUP_NAME_TAKEN'), 'Группа с таким названием уже есть.');
    expect(messageForCode('EMAIL_ALREADY_REGISTERED'), contains('уже зарегистрирован'));
  });

  test('messageForError разбирает ApiError по коду', () {
    const error = ApiError(409, 'PRICE_CHANGED');
    expect(
      messageForError(error),
      'Цена изменилась. Каталог обновлён — проверьте актуальную цену.',
    );
  });

  test('messageForError на произвольном исключении даёт запасной текст', () {
    expect(messageForError(Exception('boom')), 'Не удалось выполнить запрос.');
  });
}
