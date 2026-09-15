"""Тесты health-проб и изоляции настроек от окружения разработчика."""

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import InsecureSettingError, Settings, get_settings
from app.main import create_app

# Значение не участвует в криптографии — не через фикстуру ``keypair``,
# чтобы не зависеть от повторного импорта ``tests.conftest`` (см.
# комментарий в ``tests/test_auth.py``).
SERVICE_SECRET = "test-service-secret-" + "y" * 20


async def test_liveness_is_public(client: AsyncClient) -> None:
    """Liveness-проба отвечает 200 без авторизации: её опрашивает оркестратор."""
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_reports_checks(client: AsyncClient) -> None:
    """Readiness-проба отдаёт статус и словарь проверок зависимостей."""
    response = await client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert "status" in body
    assert "checks" in body
    assert isinstance(body["checks"], dict)


async def test_readiness_is_503_without_database(
    monkeypatch: pytest.MonkeyPatch, service_env: None
) -> None:
    """``/health/ready`` отвечает 503 без БД (критерий готовности этапа 1)."""
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "postgres")
    # Порт 1 на loopback никто не слушает: соединение отклоняется мгновенно.
    monkeypatch.setenv(
        "GAMIFICATION_DATABASE_URL",
        "postgresql+asyncpg://gamification:wrong@127.0.0.1:1/does-not-exist",
    )
    get_settings.cache_clear()
    app = create_app()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"


def test_settings_require_public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Настройки не собираются без публичного ключа проверки токенов."""
    monkeypatch.delenv("GAMIFICATION_JWT_PUBLIC_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_private_key_in_public_slot(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Приватный ключ в переменной публичного отвергается, не раскрывая значение."""
    private_key, _ = keypair
    monkeypatch.setenv("GAMIFICATION_JWT_PUBLIC_KEY", private_key)
    monkeypatch.setenv("GAMIFICATION_USERS_SERVICE_SECRET", SERVICE_SECRET)

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    assert private_key not in str(error.value)


def test_settings_reject_postgres_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Режим postgres без DSN роняет старт, а не первый запрос к БД."""
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("GAMIFICATION_DATABASE_URL", raising=False)

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


def test_settings_reject_memory_backend_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Хранилище в памяти вне local/test роняет старт."""
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("GAMIFICATION_ENVIRONMENT", "prod")

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


def test_settings_reject_short_service_secret_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Короткий служебный секрет вне local/test роняет старт (C1)."""
    monkeypatch.setenv("GAMIFICATION_ENVIRONMENT", "prod")
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("GAMIFICATION_USERS_SERVICE_SECRET", "too-short")

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    assert "too-short" not in str(error.value)


def _set_production_env(
    monkeypatch: pytest.MonkeyPatch, public_key: str, previous: str
) -> None:
    """Выставить окружение, в котором проверки длины секретов действуют."""
    monkeypatch.setenv("GAMIFICATION_ENVIRONMENT", "production")
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv(
        "GAMIFICATION_DATABASE_URL",
        "postgresql+asyncpg://gamification_app:x@127.0.0.1:1/gamification",
    )
    monkeypatch.setenv("GAMIFICATION_REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("GAMIFICATION_JWT_PUBLIC_KEY", public_key)
    monkeypatch.setenv("GAMIFICATION_USERS_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("GAMIFICATION_INTERNAL_USERS_SECRET", "internal-" + "z" * 32)
    monkeypatch.setenv("GAMIFICATION_INTERNAL_USERS_SECRET_PREVIOUS", previous)


def test_empty_previous_internal_secret_is_no_rotation(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Пустой ``_PREVIOUS`` из compose не роняет прод-старт (M1 ревью Ч3).

    Compose передаёт переменную всегда, по умолчанию пустой строкой.
    """
    _, public_key = keypair
    _set_production_env(monkeypatch, public_key, previous="")

    settings = Settings(_env_file=None)

    assert settings.internal_users_secret_previous is None


def test_short_previous_internal_secret_rejected_outside_local(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Короткий непустой ``_PREVIOUS`` вне local/test по-прежнему отвергается."""
    _, public_key = keypair
    _set_production_env(monkeypatch, public_key, previous="too-short")

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    assert "too-short" not in str(error.value)


def test_settings_ignore_env_file_in_cwd(
    tmp_path, monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Настройки читаются из процессного окружения, а не из ``.env`` cwd.

    Риск 14: скелет копирует ``env_file=".env"`` из users. Тест
    доказывает, что случайный ``.env`` в рабочей директории (в т.ч.
    оставленный разработчиком) не может подменить значения, которые
    тесты выставляют явно, — таково правило приоритета
    pydantic-settings (переменная окружения важнее файла ``.env``).
    """
    _, public_key = keypair
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GAMIFICATION_JWT_PUBLIC_KEY=not-a-key\n")
    monkeypatch.setenv("GAMIFICATION_JWT_PUBLIC_KEY", public_key)
    monkeypatch.setenv("GAMIFICATION_USERS_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("GAMIFICATION_ENVIRONMENT", "test")
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "memory")

    settings = Settings()

    assert settings.jwt_public_key.get_secret_value() == public_key


def test_env_file_in_cwd_does_not_leak_storage_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch, service_env: None
) -> None:
    """Боевой ``.env`` в cwd не подменяет DSN хранилища и denylist (риск 14).

    В отличие от ``test_settings_ignore_env_file_in_cwd``, здесь настройки
    собираются так же, как в остальных тестах — через автофикстуру
    ``service_env``, без ``_env_file=None``. Она гасит
    ``GAMIFICATION_DATABASE_URL``/``GAMIFICATION_REDIS_URL`` явным
    ``setenv("")``, а не ``delenv`` — так пустое значение остаётся
    приоритетнее файла ``.env``, который мог завести разработчик.
    """
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "GAMIFICATION_REDIS_URL=redis://bogus:6379/0\n"
        "GAMIFICATION_DATABASE_URL=postgresql+asyncpg://x:y@bogus/db\n"
        "GAMIFICATION_STORAGE_BACKEND=postgres\n"
    )
    get_settings.cache_clear()

    settings = Settings()
    app = create_app()

    assert settings.storage_backend == "memory"
    assert not (settings.database_url or "").strip()
    assert not (settings.redis_url or "").strip()
    assert app is not None


async def test_apps_do_not_share_storage() -> None:
    """Два приложения не видят учреждения друг друга.

    Состояние живёт в ``app.state``, а не в модульной переменной —
    иначе тесты и параллельные воркеры влияли бы друг на друга.
    """
    first_app = create_app()
    second_app = create_app()

    async with first_app.router.lifespan_context(first_app):
        async with second_app.router.lifespan_context(second_app):
            assert first_app.state.uow_factory is not second_app.state.uow_factory
