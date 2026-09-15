/// Ссылка-приглашение строится от origin `API_BASE_URL`
/// (`lib/api/client.dart`, `apiBaseUrl`) — паритет с вебом
/// (`services/web/src/pages/InvitationsPage.tsx`: origin, где живёт API и
/// сама страница, общий). Вынесено в отдельный файл, чтобы [buildInviteLink]
/// проверялась чистыми unit-тестами без подъёма экрана
/// (`invitations_screen_test.dart`).
library;

import '../../api/client.dart' show apiBaseUrl;

/// Строит ссылку-приглашение `<origin>/invite#<token>` от origin
/// `apiBaseUrl`: схема, хост и порт, без пути `/api/v1` — формат после
/// origin менять нельзя, это контракт напечатанного QR
/// (`.claude/knowledge/gamification-service/03-invitations.md`, F6).
///
/// `null`, если `apiBaseUrl` не разбирается или его схема не `http`/`https`
/// (пустая сборка без `API_BASE_URL`, опечатка) — тогда токен приглашения не
/// должен уйти на угаданный домен; вызывающий экран прячет ссылку и кнопку
/// копирования.
String? buildInviteLink(String apiBaseUrl, String token) {
  final uri = Uri.tryParse(apiBaseUrl);
  if (uri == null || uri.host.isEmpty) return null;
  if (uri.scheme != 'http' && uri.scheme != 'https') return null;
  final port = uri.hasPort ? ':${uri.port}' : '';
  final origin = '${uri.scheme}://${uri.host}$port';
  return '$origin/invite#$token';
}

/// Базовый адрес API для ссылки-приглашения. По умолчанию — реальный
/// [apiBaseUrl] из `lib/api/client.dart`; поле, а не прямое использование
/// константы, — чтобы тесты экрана могли задать адрес без пересборки с
/// `--dart-define` на каждый прогон (`invitations_screen_test.dart`). В
/// проде не меняется.
String inviteApiBaseUrl = apiBaseUrl;
