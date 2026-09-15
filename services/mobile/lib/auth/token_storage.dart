/// Хранилище токена и последнего выбранного учреждения — зеркало
/// `services/web/src/auth/tokenStorage.ts`.
///
/// Веб хранит в `localStorage`, у мобильного клиента аналог с шифрованием —
/// `flutter_secure_storage` (Android Keystore), решение В5 плана
/// `09-mobile-app.md`. Интерфейс асинхронный: `flutter_secure_storage` не
/// умеет синхронного чтения. Поэтому `ApiClient.tokenProvider` держит токен
/// отдельно в памяти (см. `session.dart`), а это хранилище — только для
/// сохранности между запусками приложения.
///
/// Refresh-токен (план `10-refresh.md`, Ч5) хранится тем же способом —
/// мобильный клиент предъявляет его только в теле запроса (У4), а не в
/// cookie, поэтому он не более чувствителен к каналу передачи, чем access.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Интерфейс хранилища — позволяет подменить реализацию в тестах.
abstract class TokenStorage {
  Future<String?> readToken();
  Future<void> writeToken(String token);

  /// Refresh-токен — по нему `SessionNotifier` обновляет access, когда тот
  /// истёк (`10-refresh.md`).
  Future<String?> readRefreshToken();
  Future<void> writeRefreshToken(String token);

  /// Id учреждения, выбранного в прошлый раз — для автовыбора при входе и
  /// холодном старте.
  Future<String?> readLastInstitutionId();
  Future<void> writeLastInstitutionId(String institutionId);

  /// Очищает оба токена (access и refresh) и запомненный выбор учреждения —
  /// вызывается при выходе.
  Future<void> clear();
}

/// Реализация на `flutter_secure_storage` (Android Keystore).
class SecureTokenStorage implements TokenStorage {
  SecureTokenStorage({FlutterSecureStorage? storage}) : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _tokenKey = 'gamification.accessToken';
  static const _refreshTokenKey = 'gamification.refreshToken';
  static const _lastInstitutionKey = 'gamification.lastInstitutionId';

  @override
  Future<String?> readToken() => _storage.read(key: _tokenKey);

  @override
  Future<void> writeToken(String token) => _storage.write(key: _tokenKey, value: token);

  @override
  Future<String?> readRefreshToken() => _storage.read(key: _refreshTokenKey);

  @override
  Future<void> writeRefreshToken(String token) => _storage.write(key: _refreshTokenKey, value: token);

  @override
  Future<String?> readLastInstitutionId() => _storage.read(key: _lastInstitutionKey);

  @override
  Future<void> writeLastInstitutionId(String institutionId) =>
      _storage.write(key: _lastInstitutionKey, value: institutionId);

  @override
  Future<void> clear() async {
    await _storage.delete(key: _tokenKey);
    await _storage.delete(key: _refreshTokenKey);
    await _storage.delete(key: _lastInstitutionKey);
  }
}

/// Реализация в памяти — для тестов, без платформенных каналов.
class InMemoryTokenStorage implements TokenStorage {
  String? _token;
  String? _refreshToken;
  String? _lastInstitutionId;

  @override
  Future<String?> readToken() async => _token;

  @override
  Future<void> writeToken(String token) async => _token = token;

  @override
  Future<String?> readRefreshToken() async => _refreshToken;

  @override
  Future<void> writeRefreshToken(String token) async => _refreshToken = token;

  @override
  Future<String?> readLastInstitutionId() async => _lastInstitutionId;

  @override
  Future<void> writeLastInstitutionId(String institutionId) async => _lastInstitutionId = institutionId;

  @override
  Future<void> clear() async {
    _token = null;
    _refreshToken = null;
    _lastInstitutionId = null;
  }
}
