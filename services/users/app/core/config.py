"""Настройки сервиса users.

Единственная точка чтения переменных окружения во всём сервисе.
"""

from functools import lru_cache
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Минимальная длина пароля. Общая для политики регистрации
# (``UserManager.validate_password``) и для пароля bootstrap-админа,
# чтобы два места не разъезжались.
MIN_PASSWORD_LENGTH = 8

# Заголовки PEM, по которым отличается ключ подписи от ключа проверки.
PRIVATE_KEY_HEADER = "-----BEGIN PRIVATE KEY-----"
PUBLIC_KEY_HEADER = "-----BEGIN PUBLIC KEY-----"

# Окружения, в которых реализации в памяти допустимы. Везде, кроме них,
# ``memory`` означает молчаливую потерю данных при первом же рестарте, а
# denylist в памяти — что отзыв токена не виден второй реплике. То же
# множество разрешает пустой служебный секрет внутреннего API — см.
# ``_check_internal_secret``.
MEMORY_BACKEND_ENVIRONMENTS = frozenset({"local", "test"})

# Минимальная длина служебного секрета вызывающего сервиса на
# внутреннем API. Короче — секрет перебирается за разумное время.
MIN_SERVICE_SECRET_LENGTH = 32


class InsecureSettingError(Exception):
    """Настройка не удовлетворяет требованиям безопасности.

    Намеренно не наследуется от ``ValueError``: такое исключение
    pydantic заворачивает в ``ValidationError``, а тот всегда печатает
    ``input_value`` — то есть само значение секрета — в тексте ошибки,
    независимо от ``SecretStr``. Не-``ValueError`` пробрасывается
    как есть, поэтому наружу уходит только требование к значению.
    """


class Settings(BaseSettings):
    """Конфигурация сервиса, читаемая из окружения и файла .env."""

    model_config = SettingsConfigDict(
        env_prefix="USERS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "users"
    environment: str = "local"
    log_level: str = "INFO"

    # Публичный префикс, под которым сервис виден снаружи. Сам сервис
    # свои маршруты им не префиксует — это делает шлюз; значение нужно
    # только для того, чтобы OpenAPI и /docs показывали адреса, по
    # которым клиент реально ходит. Пусто при прямом обращении к порту
    # сервиса (локальный запуск, тесты, пробы оркестратора).
    root_path: str = ""

    # Подпись асимметричная: приватный ключ есть только у этого сервиса,
    # остальные проверяют токены публичным и подделать их не могут. При
    # симметричном ключе любой сервис, способный проверить токен, мог бы
    # его и выпустить.
    #
    # Форма проверяется валидаторами ниже, а не ``Field(pattern=...)``:
    # ограничение поля попадает в текст ValidationError вместе со
    # значением (``input_value=...``), то есть с ключом, — ровно так уже
    # утекал секрет подписи. Значений по умолчанию нет: оба поля
    # обязательны.
    jwt_private_key: SecretStr
    # ``SecretStr`` не потому, что публичный ключ секретен — он по
    # определению открыт. Потому что в это поле по ошибке попадает
    # приватный ключ (соседние переменные, копипаста), и тогда жалоба на
    # неверный формат напечатала бы его целиком.
    jwt_public_key: SecretStr
    jwt_algorithm: str = "RS256"
    # gt=0: ``fastapi_users.jwt.generate_jwt`` добавляет claim ``exp``
    # только при истинном ``lifetime_seconds``. При значении 0 выдавался
    # бы токен вовсе без ``exp``, который ``read_token`` принимает
    # бессрочно, — вечный bearer при отсутствующем пока отзыве.
    # 15 минут. Короткий срок — плата за отсутствие мгновенного отзыва:
    # столько живёт украденный токен и столько же держится устаревшая
    # роль. Длинная сессия обеспечивается refresh-токеном, а не
    # растягиванием этого значения.
    jwt_lifetime_seconds: int = Field(900, gt=0)

    bootstrap_admin_email: str | None = None
    bootstrap_admin_password: SecretStr | None = None

    # Служебный секрет вызывающего (gamification) на внутренний выпуск
    # токена в контексте учреждения (``POST
    # /internal/tokens/institution-context``). Умолчание — пустая
    # строка, а не обязательное поле: в local/test эндпоинт должен быть
    # доступен для запуска без docker, но тогда любой вызов отвергается
    # (пустой секрет никогда не совпадает, см. ``_check_internal_secret``).
    internal_gamification_secret: SecretStr = SecretStr("")
    # Второе значение на время ротации: users принимает оба секрета, пока
    # gamification не переведена на новый. ``None`` — ротация не идёт.
    internal_gamification_secret_previous: SecretStr | None = None

    # Обратное направление (план 10-refresh, У7): секрет, которым users
    # представляется gamification на ``POST
    # /internal/memberships/resolve``. Отдельный от
    # ``internal_gamification_secret`` намеренно — общий секрет на оба
    # направления позволил бы утечке одного выдать себя за любой из
    # сервисов. У этого секрета нет своего ``_PREVIOUS``: ротацию
    # принимающая сторона (gamification, ``_PREVIOUS`` там) — здесь
    # достаточно единственного текущего значения, которое отправляется,
    # а не проверяется.
    gamification_service_secret: SecretStr = SecretStr("")
    # Адрес gamification для внутренних вызовов. Пусто — обращение
    # невозможно технически, и refresh обязан обработать это так же, как
    # недоступность gamification (вопрос 2 = А): без записи в
    # институт/сеть городить отдельную ошибку конфигурации не за чем —
    # эффект наружу одинаков.
    gamification_internal_url: str | None = None

    # Окно повторного предъявления refresh-токена (вопрос 3 = А): токен,
    # чей преемник ещё не предъявлен, в это окно после использования
    # проворачивает ротацию ещё раз вместо гашения сессии. Компенсирует
    # потерянный ответ на мобильной сети (риск 3).
    refresh_reuse_grace_seconds: int = Field(30, gt=0)

    # Сроки жизни refresh-сессии по типу клиента (вопрос 4 = Б): у веба
    # короче — общие компьютеры в школах, у мобильного — дольше, это
    # личное устройство. ``idle`` — скользящее окно простоя, продлевается
    # каждой успешной ротацией; ``absolute`` фиксируется при создании
    # сессии и не продлевается никогда.
    refresh_web_idle_days: int = Field(7, gt=0)
    refresh_web_absolute_days: int = Field(30, gt=0)
    refresh_mobile_idle_days: int = Field(30, gt=0)
    refresh_mobile_absolute_days: int = Field(90, gt=0)

    # ``HttpOnly; SameSite=Strict`` всегда; ``Secure`` — по этой настройке
    # (У5). ``False`` допустим только в local/test: без TLS в остальных
    # окружениях cookie с refresh-токеном ушла бы открытым текстом.
    refresh_cookie_secure: bool = True

    # Какая реализация хранилища подключается в ``app/api/deps.py``.
    # Умолчание — ``postgres``: забытая переменная не должна тихо дать
    # хранилище в памяти, теряющее данные при рестарте. ``memory``
    # выставляется тестами и допустим только в local/test — см.
    # ``_check_storage_backend``.
    storage_backend: Literal["postgres", "memory"] = "postgres"
    # DSN для async-движка: postgresql+asyncpg://user:password@host:port/db
    # Обязателен при ``storage_backend=postgres``. Пароль внутри URL —
    # причина, по которой пустое значение отвергается собственным
    # исключением, а не ValidationError: см. ``InsecureSettingError``.
    database_url: str | None = None
    # Адрес Redis для denylist отозванных токенов:
    # redis://host:port/db. Пусто — denylist живёт в памяти процесса;
    # допустимо только в local/test, см. ``_check_denylist_backend``.
    redis_url: str | None = None

    @field_validator("root_path")
    @classmethod
    def _normalize_root_path(cls, value: str) -> str:
        """Привести префикс к виду без завершающего слэша.

        FastAPI склеивает ``root_path`` с путями маршрутов как есть,
        поэтому ``/api/v1/`` дало бы в схеме двойной слэш.
        """
        return value.rstrip("/")

    @field_validator("jwt_private_key")
    @classmethod
    def _check_private_key(cls, value: SecretStr) -> SecretStr:
        """Убедиться, что подан приватный ключ, не раскрывая значение.

        Проверка формы, а не криптографической валидности: без неё
        неверный ключ роняет не старт сервиса, а первый же логин —
        пятисоткой вместо внятного отказа.
        """
        if not value.get_secret_value().lstrip().startswith(PRIVATE_KEY_HEADER):
            raise InsecureSettingError(
                f"JWT private key must be a PEM block starting with "
                f"{PRIVATE_KEY_HEADER!r}"
            )
        return value

    @field_validator("jwt_public_key")
    @classmethod
    def _check_public_key(cls, value: SecretStr) -> SecretStr:
        """Убедиться, что подан именно публичный ключ.

        Отдельная проверка нужна не ради формата: в это поле по ошибке
        попадает приватный ключ, и тогда сервис молча раздаёт его всем,
        кому положен публичный.
        """
        text = value.get_secret_value().lstrip()
        if text.startswith(PRIVATE_KEY_HEADER):
            raise InsecureSettingError(
                "JWT public key setting contains a PRIVATE key. "
                "Its value is distributed to other services — rotate the key pair"
            )
        if not text.startswith(PUBLIC_KEY_HEADER):
            raise InsecureSettingError(
                f"JWT public key must be a PEM block starting with "
                f"{PUBLIC_KEY_HEADER!r}"
            )
        return value

    @field_validator("bootstrap_admin_password")
    @classmethod
    def _check_bootstrap_admin_password(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        """Проверить длину пароля админа, не раскрывая его значение.

        ``None`` допустим: тогда сид bootstrap-админа просто не
        выполняется. Пустая строка означает то же самое и приводится к
        ``None``: compose передаёт переменную всегда, и незаданный
        пароль приезжает пустым значением, а не отсутствием переменной.
        """
        if value is None:
            return None
        secret = value.get_secret_value()
        if not secret.strip():
            return None
        if len(secret) < MIN_PASSWORD_LENGTH:
            raise InsecureSettingError(
                "Bootstrap admin password is too short: "
                f"at least {MIN_PASSWORD_LENGTH} characters required"
            )
        return value

    @model_validator(mode="after")
    def _check_storage_backend(self) -> Self:
        """Проверить, что выбранная реализация хранилища работоспособна.

        Проверка межполевая, поэтому это ``model_validator``: правила
        связывают ``storage_backend`` с ``database_url`` и
        ``environment``. Оба нарушения роняют создание ``Settings``, то
        есть старт сервиса, — тихо работать с неверным хранилищем хуже,
        чем не стартовать.

        ``InsecureSettingError`` вместо ``ValueError``: DSN содержит
        пароль к БД, а ``ValidationError`` печатает входные значения —
        по той же причине, что и у ключей подписи.
        """
        if self.storage_backend == "postgres" and not (self.database_url or "").strip():
            raise InsecureSettingError(
                "USERS_DATABASE_URL is required when USERS_STORAGE_BACKEND=postgres"
            )
        if (
            self.storage_backend == "memory"
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "USERS_STORAGE_BACKEND=memory loses all data on restart and is "
                f"allowed only when USERS_ENVIRONMENT is one of: {allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_denylist_backend(self) -> Self:
        """Проверить, что отзыв токенов будет работать в этом окружении.

        Правило симметрично правилу хранилища: пустой ``USERS_REDIS_URL``
        означает denylist в памяти процесса, а такой отзыв не виден ни
        второй реплике, ни самому процессу после рестарта. В local и
        test это ровно то, что нужно (тесты выхода не требуют поднятого
        Redis), в остальных окружениях — молча неработающий отзыв.

        ``InsecureSettingError`` вместо ``ValueError``: URL Redis может
        содержать пароль, а ``ValidationError`` печатает входные
        значения.
        """
        if (
            not (self.redis_url or "").strip()
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "USERS_REDIS_URL is required: without it revoked tokens are "
                "tracked in process memory, which no other replica sees. "
                f"Empty value is allowed only when USERS_ENVIRONMENT is one of: "
                f"{allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_internal_secret(self) -> Self:
        """Проверить длину служебного секрета внутреннего API.

        Секрет выпускает токены по запросу вызывающего сервиса, поэтому
        короткое или пустое значение вне ``local``/``test`` роняет старт
        так же, как и ключи подписи. В ``local``/``test`` пустой секрет
        допустим — тогда любой внутренний вызов отвергается
        (``SERVICE_AUTH_FAILED``): пустая строка сравнением никогда не
        совпадает, см. проверку вызывающего в
        ``app/api/internal/internal_router.py``.

        ``InsecureSettingError`` вместо ``ValueError`` — по той же
        причине, что и у ключей подписи: секрет не должен попасть в
        текст ошибки.
        """
        secret = self.internal_gamification_secret.get_secret_value()
        if (
            len(secret) < MIN_SERVICE_SECRET_LENGTH
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "USERS_INTERNAL_GAMIFICATION_SECRET must be at least "
                f"{MIN_SERVICE_SECRET_LENGTH} characters outside of: {allowed}"
            )
        if self.internal_gamification_secret_previous is not None:
            previous = self.internal_gamification_secret_previous.get_secret_value()
            if (
                len(previous) < MIN_SERVICE_SECRET_LENGTH
                and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
            ):
                allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
                raise InsecureSettingError(
                    "USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS must be at "
                    f"least {MIN_SERVICE_SECRET_LENGTH} characters outside "
                    f"of: {allowed}"
                )
        return self

    @model_validator(mode="after")
    def _check_gamification_service_secret(self) -> Self:
        """Проверить длину секрета users → gamification (У7).

        Симметрично ``_check_internal_secret``: пустой секрет вне
        local/test роняет старт, а не тихо шлёт пустой заголовок,
        который gamification закономерно отвергнет с
        ``SERVICE_AUTH_FAILED`` — то есть refresh с институтом молча
        деградировал бы до «gamification недоступна» в проде.
        """
        secret = self.gamification_service_secret.get_secret_value()
        if (
            len(secret) < MIN_SERVICE_SECRET_LENGTH
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "USERS_GAMIFICATION_SERVICE_SECRET must be at least "
                f"{MIN_SERVICE_SECRET_LENGTH} characters outside of: {allowed}"
            )
        return self

    @model_validator(mode="after")
    def _check_refresh_cookie_secure(self) -> Self:
        """Запретить ``Secure=false`` у refresh-cookie вне local/test.

        Без TLS в остальных окружениях refresh-токен, самый
        долгоживущий секрет клиента, ушёл бы по HTTP открытым текстом.
        """
        if (
            not self.refresh_cookie_secure
            and self.environment not in MEMORY_BACKEND_ENVIRONMENTS
        ):
            allowed = ", ".join(sorted(MEMORY_BACKEND_ENVIRONMENTS))
            raise InsecureSettingError(
                "USERS_REFRESH_COOKIE_SECURE=false is allowed only when "
                f"USERS_ENVIRONMENT is one of: {allowed}"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Вернуть закэшированный экземпляр настроек."""
    return Settings()
