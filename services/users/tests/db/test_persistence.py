"""Персистентность и старт сервиса на реальной БД.

Проверяется то, что на in-memory проверить нельзя по построению: там
есть обратный тест ``test_apps_do_not_share_storage``, и он обязан
оставаться верным — данные принадлежат процессу. Здесь данные
принадлежат базе, поэтому «рестарт» приложения их не теряет.
"""

from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.main import create_app
from app.repositories.models import User

EMAIL = "persisted@example.com"
PASSWORD = "correct-horse-battery-staple"
BOOTSTRAP_EMAIL = "owner@example.com"
BOOTSTRAP_PASSWORD = "correct-horse-battery-staple"

Register = Callable[..., Awaitable[Response]]


async def test_registered_user_survives_app_restart(
    register: Register, client: AsyncClient
) -> None:
    """Пользователь, заведённый одним приложением, входит во втором.

    Второе приложение — отдельный ``create_app()`` со своим движком и
    своим пулом: ровно то, что происходит при рестарте контейнера и при
    второй реплике. На in-memory этот тест невозможен.
    """
    created = await register(EMAIL, PASSWORD)
    assert created.status_code == 201, created.text

    restarted: FastAPI = create_app()
    async with restarted.router.lifespan_context(restarted):
        transport = ASGITransport(app=restarted)
        async with AsyncClient(transport=transport, base_url="http://restart") as http:
            response = await http.post(
                "/users/auth/jwt/login",
                data={"username": EMAIL, "password": PASSWORD},
            )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_readiness_reports_live_database(client: AsyncClient) -> None:
    """Readiness при живой БД отвечает 200 и отмечает проверку базы.

    Проба делает настоящий ``SELECT 1`` в отдельной сессии, поэтому
    зелёный ответ здесь означает работающее соединение, а не то, что
    объект хранилища создан.
    """
    response = await client.get("/health/ready")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"]["database"] == "ok"


async def test_bootstrap_seed_is_idempotent(
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Два старта подряд не создают дубль владельца и не падают.

    На in-memory повторный старт всегда видел пустое хранилище, поэтому
    идемпотентность сида там не проверялась вовсе: ветка «учётка уже
    есть» впервые исполняется именно здесь.
    """
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_EMAIL", BOOTSTRAP_EMAIL)
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_PASSWORD", BOOTSTRAP_PASSWORD)
    # Сид читает настройки в lifespan, а они кешированы: без сброса
    # приложение стартовало бы со старым (пустым) значением.
    get_settings.cache_clear()

    for _ in range(2):
        app = create_app()
        async with app.router.lifespan_context(app):
            pass

    async with session_factory() as session:
        owners = await session.execute(
            select(User).where(User.email == BOOTSTRAP_EMAIL)
        )

    owner_rows = owners.scalars().all()
    assert len(owner_rows) == 1
    assert owner_rows[0].is_superuser is True
