/// Минимальные заглушки экранов Ч3 — сами экраны делает Ч5.
///
/// [ScreenPlaceholder] — просто название экрана: маршрут существует и на
/// него можно попасть, содержимое ещё не реализовано.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/session.dart';
import '../i18n/error_messages.dart';
import '../ui/screen_state.dart';

class ScreenPlaceholder extends StatelessWidget {
  const ScreenPlaceholder(this.title, {super.key});

  final String title;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(child: Text(title)),
    );
  }
}

/// Показывается, пока сессия ещё не определена (`SessionStatus.loading`) —
/// аналог `AuthPending` веба: приложение не шлёт запросов, пока идёт
/// проверка сохранённого токена.
///
/// Если холодный старт упал не на 401 (сеть, таймаут, 5xx, нечитаемый
/// ответ), `SessionState.startupError` не пуст — вместо вечного спиннера
/// показываем ошибку с «Повторить» (`SessionNotifier.retryStart`).
class AuthPendingScreen extends ConsumerWidget {
  const AuthPendingScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final error = ref.watch(sessionProvider.select((state) => state.startupError));
    if (error == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    return Scaffold(
      body: Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: ScreenStateError(
            message: messageForError(error),
            onRetry: () => ref.read(sessionProvider.notifier).retryStart(),
          ),
        ),
      ),
    );
  }
}
