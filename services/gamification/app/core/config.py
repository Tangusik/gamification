"""Настройки сервиса gamification.

Единственная точка чтения переменных окружения во всём сервисе. Схема
повторяет ``services/users/app/core/config.py`` — тот же
``InsecureSettingError`` и та же причина для него: pydantic
``ValidationError`` печатает ``input_value`` даже для ``SecretStr``.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Заголовки PEM. Публичный ключ отличается от приватного форматом блока:
# в переменную публичного по ошибке может попасть приватный (копипаста
# из .env сервиса users), и тогда сервис принимал бы его молча.
PRIVATE_KEY_HEADER = "-----BEGIN PRIVATE KEY-----"
PUBLIC_KEY_HEADER = "-----BEGIN PUBLIC KEY-----"

# Окружения, в которых реализации в памяти и короткий служебный секрет
# допустимы. Везде, кроме них, это либо молчаливая потеря данных при
# рестарте, либо секрет, который проще подобрать.
MEMORY_BACKEND_ENVIRONMENTS = frozenset({"local", "test"})

# Минимальная длина служебного секрета сервис-сервис (C1).
MIN_SERVICE_SECRET_LENGTH = 32


class InsecureSettingError(Exception):
    """Настройка не удовлетворяет требованиям безопасности.

    Намеренно не наследуется от ``ValueError`` — см. одноимённое
    исключение в ``services/users/app/core/config.py``: та же причина.
    """


class Settings(BaseSettings):
    """Конфигурация сервиса, читаемая из окружения и файла .env."""

    model_config = SettingsConfigDict(
        env_prefix="GAMIFICATION_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "gamification"
    environment: str = "local"
    log_level: str = "INFO"

    # Публичный префикс, под которым сервис виден снаружи. Сам сервис
    # свои маршруты им не префиксует — это делает шлюз; значение нужно
    # только для того, чтобы OpenAPI и /docs показывали адреса, по
    # которым клиент реально ходит.
    root_path: str = ""

    # Публичный ключ проверки токенов (J1): то же значение, что
    # USERS_JWT_PUBLIC_KEY. Приватного ключа в этом сервисе нет и быть
    # не может — gamification не выпускает токены, только проверяет.
    jwt_public_key: SecretStr
    jwt_algorithm: str = "RS256"
    # Аудитория токена — строка контракта, общая для всех сервисов.
    # Расхождение с users даёт молчаливый 401 на всём сервисе (риск 8).
    jwt_audience: list[str] = Field(default_factory=lambda: ["fastapi-users:auth"])

    # Какая реализация хранилища подключается в ``app/api/deps.py``.
    # Умолчание — ``postgres``: забытая переменная не должна тихо дать
    # хранилище в памяти, теряющее данные при рестарте.
    storage_backend: Literal["postgres", "memory"] = "postgres"
    # DSN своей базы (I1: своя база и роль, без доступа к базе users).
    database_url: str | None = None
    # Адрес Redis users для чтения denylist (K1). Пусто — проверка
    # отзыва не выполняется; допустимо только в local/test.
    redis_url: str | None = None

    # Внутренний вызов users на выпуск токена в контексте (раздел 4).
    users_internal_url: str = "http://users:8000"
    # Служебный секрет заголовка X-Service-Secret (C1).
    users_service_secret: SecretStr

    @field_validator("root_path")
    @classmethod
    def _normalize_root_path(cls, value: str) -> str:
        """Привести префикс к виду без завершающего слэша."""
        return value.rstrip("/")

    @field_validator("jwt_public_key")
    @classmethod
    def _check_public_key(cls, value: SecretStr) -> SecretStr:
        """Убедиться, что подан именно публичный ключ, не раскрывая значение."""
        text = value.get_secret_value().lstrip()
        if text.startswith(PRIVATE_KEY_HEADER):
            raise InsecureSettingError(
                "GAMIFICATION_JWT_PUBLIC_KEY contains a PRIVATE key. "
                "This service only verifies tokens; a private key here is "
                "always a configuration mistake"
            )
        if not text.startswith(PUBLIC_KEY_HEADER):
            raise InsecureSettingError(
                f"GAMIFICATION_JWT_PUBLIC_KEY must be a PEM block starting "
                f"with {PUBLIC_KEY_HEADER!r}"
            )
        return value

    @model_validator(mode="after")
    def _check_storage_backend(self) -> Self:
        """Проверить, что выбранная реализация хранилища работоспособна."""
        if self.storage_backend == "postgres" and not (self.database_url or "").strip():
            raise InsecureSettingError(
                "GAMIFICATION_DATABASE_URL is required when "
                "GAMIFICATION_STORAGE_BACKEND=postgres"
            )
        if (
            self.storage_backend == "memory"
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "GAMIFICATION_STORAGE_BACKEND=memory loses all data on "
                f"restart and is allowed only when GAMIFICATION_ENVIRONMENT "
                f"is one of: {allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_denylist_backend(self) -> Self:
        """Проверить, что пустой ``REDIS_URL`` допустим в этом окружении (K1)."""
        if (
            not (self.redis_url or "").strip()
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "GAMIFICATION_REDIS_URL is required: without it revoked "
                "tokens from users are not checked at all. Empty value is "
                f"allowed only when GAMIFICATION_ENVIRONMENT is one of: "
                f"{allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_service_secret(self) -> Self:
        """Проверить длину служебного секрета, не раскрывая значение (C1)."""
        secret = self.users_service_secret.get_secret_value()
        if (
            len(secret) < MIN_SERVICE_SECRET_LENGTH
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "GAMIFICATION_USERS_SERVICE_SECRET must be at least "
                f"{MIN_SERVICE_SECRET_LENGTH} characters outside of: {allowed}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Вернуть закэшированный экземпляр настроек."""
    return Settings()
