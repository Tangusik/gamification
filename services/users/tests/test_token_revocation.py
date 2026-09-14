"""Тесты отзыва токенов: выход из системы и поведение при отказе denylist.

Все тесты идут на реализации denylist в памяти и не требуют поднятого
Redis — ровно та причина, по которой ``InMemoryTokenDenylist``
существует.
"""

import logging
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_token_denylist
from app.core.config import InsecureSettingError, Settings, get_settings
from app.repositories.denylist import InMemoryTokenDenylist, TokenDenylist


class RecordingDenylist(InMemoryTokenDenylist):
    """Denylist, запоминающий, с каким TTL его просили погасить токен."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, int]] = []

    async def revoke(self, token_id: str, ttl_seconds: int) -> None:
        self.calls.append((token_id, ttl_seconds))
        await super().revoke(token_id, ttl_seconds)


class BrokenDenylist:
    """Недоступный denylist: любая операция заканчивается отказом.

    Повторяет наблюдаемое поведение упавшего Redis — исключение на
    каждом обращении.
    """

    async def revoke(self, token_id: str, ttl_seconds: int) -> None:
        raise ConnectionError("denylist is down")

    async def is_revoked(self, token_id: str) -> bool:
        raise ConnectionError("denylist is down")

    async def ping(self) -> bool:
        return False

    async def close(self) -> None:
        return None


@pytest.fixture
def use_denylist(app: FastAPI) -> Callable[[TokenDenylist], None]:
    """Подменить denylist приложения на время одного теста.

    Подмена идёт через ``dependency_overrides`` в точке шва
    (``get_token_denylist``), а не правкой ``app.state``: так тест
    проверяет ровно тот путь, которым denylist попадает в стратегию в
    рантайме.
    """

    def _use(denylist: TokenDenylist) -> None:
        app.dependency_overrides[get_token_denylist] = lambda: denylist

    return _use


async def test_logout_revokes_token(
    client: AsyncClient, auth_headers: Callable[..., Awaitable[dict[str, str]]]
) -> None:
    """После выхода из системы токен перестаёт открывать ``/users/me``.

    Главный тест части: без denylist ``logout`` возвращал бы те же 204,
    но токен продолжал бы работать до истечения срока.
    """
    headers = await auth_headers()
    assert (await client.get("/users/me", headers=headers)).status_code == 200

    logout = await client.post("/users/auth/jwt/logout", headers=headers)

    assert logout.status_code == 204, logout.text
    assert (await client.get("/users/me", headers=headers)).status_code == 401


async def test_revocation_ttl_does_not_outlive_token(
    client: AsyncClient,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
    use_denylist: Callable[[TokenDenylist], None],
) -> None:
    """Запись отзыва живёт не дольше самого токена.

    Иначе denylist рос бы неограниченно: токен уже не примут по ``exp``,
    а ключ о нём остался бы навсегда.
    """
    denylist = RecordingDenylist()
    use_denylist(denylist)
    headers = await auth_headers()

    await client.post("/users/auth/jwt/logout", headers=headers)

    assert len(denylist.calls) == 1
    _, ttl_seconds = denylist.calls[0]
    assert 0 < ttl_seconds <= get_settings().jwt_lifetime_seconds


async def test_unavailable_denylist_lets_valid_token_through(
    client: AsyncClient,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
    use_denylist: Callable[[TokenDenylist], None],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Отказ denylist не закрывает сервис, но обязан быть виден в логе.

    Fail-open — решение владельца проекта: ущерб ограничен остатком
    жизни токена, тогда как fail-closed клал бы всю школу на каждый
    рестарт хранилища. Тест закрепляет это поведение, чтобы fail-closed
    не пробрался обратно незаметно.
    """
    headers = await auth_headers()
    use_denylist(BrokenDenylist())

    with caplog.at_level(logging.ERROR, logger="app.auth.strategy"):
        response = await client.get("/users/me", headers=headers)

    assert response.status_code == 200
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors, "Отказ denylist обязан попасть в лог уровнем error"
    assert any("denylist" in record.getMessage() for record in errors)


async def test_revoking_one_token_keeps_the_other_alive(
    client: AsyncClient,
    get_token: Callable[..., Awaitable[str]],
) -> None:
    """Гашение одного токена не трогает второй токен того же пользователя.

    Ключ отзыва — ``jti``, уникальный для выпуска, а не идентификатор
    пользователя. «Выйти везде» потребовало бы серверных сессий,
    которых в сервисе нет.
    """
    first = await get_token()
    second = await get_token()
    assert first != second

    logout = await client.post(
        "/users/auth/jwt/logout", headers={"Authorization": f"Bearer {first}"}
    )
    assert logout.status_code == 204, logout.text

    revoked = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {first}"}
    )
    survivor = await client.get(
        "/users/me", headers={"Authorization": f"Bearer {second}"}
    )

    assert revoked.status_code == 401
    assert survivor.status_code == 200


def test_settings_reject_empty_redis_url_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой ``USERS_REDIS_URL`` вне local/test роняет старт.

    Симметрично правилу для хранилища: denylist в памяти процесса не
    виден ни второй реплике, ни самому процессу после рестарта, то есть
    отзыв токенов молча не работал бы.
    """
    monkeypatch.delenv("USERS_REDIS_URL", raising=False)
    monkeypatch.setenv("USERS_ENVIRONMENT", "prod")
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("USERS_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/users")

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)
