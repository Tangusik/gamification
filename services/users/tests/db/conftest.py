"""Фикстуры тестов против реальной PostgreSQL.

Здесь переопределяется ровно то, что отличает этот пакет от остальных
тестов: режим хранилища (``postgres`` вместо ``memory``) и способ
получить чистое состояние. В остальных тестах чистое состояние — это
новое приложение, потому что данные живут в ``app.state``; здесь данные
переживают приложение, поэтому схема пересоздаётся фикстурой перед
каждым тестом.

Autouse-фикстура ``service_env`` из ``tests/conftest.py`` не правится:
``db_env`` запрашивает её и перекрывает две переменные поверх. Правка
общей фикстуры сделала бы весь остальной прогон зависимым от docker.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from conftest import (
    TEST_DATABASE_URL_ENV,
    postgres_schema,
    require_test_database_url,
)
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.main import create_app
from app.repositories.database import create_session_factory

PACKAGE_DIR = Path(__file__).parent


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Пометить весь пакет маркером ``db`` и пропустить его без базы.

    Хук, а не ``pytestmark`` в каждом модуле: ``pytestmark`` в
    ``conftest.py`` не действует, а повторять его в каждом новом файле
    рано или поздно забудут — и тест против реальной БД поедет в
    обычный прогон, где docker не поднят. Отсутствие DSN даёт ``skip``
    всего пакета, а не ошибку: явный запуск ``pytest -m db`` без docker
    должен сообщать причину, а не падать в фикстуре.
    """
    skip_without_db = pytest.mark.skip(
        reason=f"{TEST_DATABASE_URL_ENV} не задан: нужен поднятый docker-стек"
    )
    url_is_set = bool((os.environ.get(TEST_DATABASE_URL_ENV) or "").strip())
    for item in items:
        if PACKAGE_DIR not in Path(str(item.path)).parents:
            continue
        item.add_marker(pytest.mark.db)
        if not url_is_set:
            item.add_marker(skip_without_db)


@pytest.fixture
def db_env(service_env: None, monkeypatch: pytest.MonkeyPatch) -> str:
    """Переключить сервис на реальную БД на время одного теста.

    ``service_env`` запрашивается явно, чтобы порядок был гарантирован:
    она выставляет ``memory``, а эта фикстура — ``postgres`` поверх.
    ``cache_clear`` обязателен: ``get_settings`` кеширован через
    ``lru_cache``, и без сброса приложение подняло бы хранилище в
    памяти, а тест молча проверял бы не то.
    """
    url = require_test_database_url()
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("USERS_DATABASE_URL", url)
    get_settings.cache_clear()
    return url


@pytest.fixture
async def db_engine(db_env: str) -> AsyncIterator[AsyncEngine]:
    """Чистая схема в тестовой базе и отдельный движок поверх неё.

    Движок тестовый и с приложением не разделяется: у приложения свой,
    созданный в ``lifespan``. Нужен он для прямых проверок того, что в
    базе действительно лежит.
    """
    async with postgres_schema(db_env) as engine:
        yield engine


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Фабрика сессий тестового движка."""
    return create_session_factory(db_engine)


@pytest.fixture
def app(db_engine: AsyncEngine) -> FastAPI:
    """Приложение поверх реальной БД.

    Переопределяет фикстуру из ``tests/conftest.py``. Зависимость от
    ``db_engine`` — не только ради настроек: схема обязана существовать
    до старта приложения, а очистка данных — происходить между тестами.
    """
    return create_app()
