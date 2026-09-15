/// Ссылка-приглашение, которую аноним вставил на `/invite` и с которой ушёл
/// на вход или регистрацию (`InviteScreen._goAuth`).
///
/// Хранится только в памяти текущего процесса (Riverpod `StateProvider`), а
/// не на диске и не в URL: находка С1 ревью безопасности (`09-mobile-app.md`,
/// Ч6) — explicit intent на `/invite?link=…` из чужого приложения не должен
/// уметь подставить свой токен и запустить автоприём. Значение читает и
/// очищает только сам `InviteScreen` после возврата со входа/регистрации.
library;

// `StateProvider` в Riverpod 3 вынесен в отдельный импорт `legacy.dart` —
// для одного изменяемого значения без бизнес-логики он проще самодельного
// `Notifier`.
import 'package:flutter_riverpod/legacy.dart';

final pendingInviteProvider = StateProvider<String?>((ref) => null);
