"""Тесты health-проб, валидации настроек и изоляции состояния."""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.core.config import InsecureSettingError, Settings
from app.main import create_app

EMAIL = "health@example.com"
PASSWORD = "correct-horse-battery-staple"


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


def test_settings_require_signing_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Настройки не собираются без пары ключей подписи.

    ``_env_file=None`` отключает чтение ``.env`` рядом с сервисом:
    результат теста не должен зависеть от окружения разработчика.
    """
    monkeypatch.delenv("USERS_JWT_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("USERS_JWT_PUBLIC_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_reject_malformed_private_key(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Ключ не в формате PEM роняет старт, а не первый логин.

    Значение в текст ошибки не попадает: сообщение уходит в stdout
    контейнера и в лог CI.
    """
    malformed = "definitely-not-a-pem-key"
    monkeypatch.setenv("USERS_JWT_PRIVATE_KEY", malformed)
    monkeypatch.setenv("USERS_JWT_PUBLIC_KEY", keypair[1])

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    assert malformed not in str(error.value)


def test_settings_reject_private_key_in_public_slot(
    monkeypatch: pytest.MonkeyPatch, keypair: tuple[str, str]
) -> None:
    """Приватный ключ в переменной публичного отвергается.

    Худшая из ошибок конфигурации в асимметричной схеме: значение этой
    переменной раздаётся остальным сервисам, и подпись перестала бы
    отличать выпуск от проверки. Ключ в текст ошибки не попадает.
    """
    private_key, _ = keypair
    monkeypatch.setenv("USERS_JWT_PRIVATE_KEY", private_key)
    monkeypatch.setenv("USERS_JWT_PUBLIC_KEY", private_key)

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    assert private_key not in str(error.value)


def test_settings_reject_postgres_without_database_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Режим postgres без DSN роняет старт, а не первый запрос к БД.

    Умолчание ``storage_backend`` — ``postgres``, поэтому забытый
    ``USERS_DATABASE_URL`` обязан быть отказом на этапе настроек: иначе
    сервис поднялся бы и отвечал пятисотками.
    """
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "postgres")
    monkeypatch.delenv("USERS_DATABASE_URL", raising=False)

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


def test_settings_reject_memory_backend_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Хранилище в памяти вне local/test роняет старт.

    Защита от прода, молча теряющего всех пользователей при рестарте
    контейнера.
    """
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("USERS_ENVIRONMENT", "prod")

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


async def test_apps_do_not_share_storage() -> None:
    """Два приложения не видят пользователей друг друга.

    Подтверждает, что состояние живёт в ``app.state``, а не в модульной
    глобальной переменной: иначе тесты и параллельные воркеры влияли бы
    друг на друга.
    """
    first_app: FastAPI = create_app()
    second_app: FastAPI = create_app()

    async with first_app.router.lifespan_context(first_app):
        transport = ASGITransport(app=first_app)
        async with AsyncClient(transport=transport, base_url="http://first") as first:
            created = await first.post(
                "/users/auth/register", json={"email": EMAIL, "password": PASSWORD}
            )
            assert created.status_code == 201, created.text

        async with second_app.router.lifespan_context(second_app):
            transport = ASGITransport(app=second_app)
            base_url = "http://second"
            async with AsyncClient(transport=transport, base_url=base_url) as second:
                login = await second.post(
                    "/users/auth/jwt/login",
                    data={"username": EMAIL, "password": PASSWORD},
                )

    assert first_app.state.user_storage is not second_app.state.user_storage
    assert login.status_code == 400
    assert login.json()["detail"] == "LOGIN_BAD_CREDENTIALS"
