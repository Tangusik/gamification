"""Проверка: ``alembic upgrade head`` даёт ту же схему, что модели (раздел 7).

Требует поднятого docker-стека и ``GAMIFICATION_TEST_DATABASE_URL`` —
без переменной пропускается ``tests/db/conftest.py``. Гонять сейчас не
требуется: тестовая база ``gamification_test`` заводится инфраструктурной
частью этапа отдельно.
"""

import os
import subprocess
import sys
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.repositories import models  # noqa: F401  регистрирует таблицы в metadata
from app.repositories.database import Base, create_engine
from tests.db.conftest import assert_connected_to_test_database

SERVICE_DIR = Path(__file__).resolve().parents[2]


async def _assert_url_is_actually_test_database(database_url: str) -> None:
    """Второй рубеж Т1 (L1) перед ``alembic upgrade``/``downgrade``.

    Проверка URL (``require_test_owner_database_url``) не видит подмену
    имени базы через query-параметры драйвера — здесь спрашивается сама
    СУБД, к чему открывается соединение на самом деле.
    """
    engine = create_engine(database_url)
    try:
        async with engine.connect() as connection:
            await assert_connected_to_test_database(connection)
    finally:
        await engine.dispose()


async def test_migration_matches_models(db_owner_url: str) -> None:
    """Цикл ``0004`` под ролью-владельцем (В4/P2 плана 07a).

    У роли приложения нет прав DDL (У3) — миграции всегда идут под
    ``gamification`` (У1), поэтому и сверка со схемой строится тем же
    DSN, а не ``db_env`` (роль приложения).
    """
    env = dict(os.environ)
    env["GAMIFICATION_DATABASE_URL"] = db_owner_url
    env["GAMIFICATION_STORAGE_BACKEND"] = "postgres"

    await _assert_url_is_actually_test_database(db_owner_url)
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVICE_DIR,
        env=env,
        check=True,
    )

    engine = create_engine(db_owner_url)
    try:

        def _compare(sync_connection):
            context = MigrationContext.configure(sync_connection)
            return compare_metadata(context, Base.metadata)

        async with engine.connect() as connection:
            diff = await connection.run_sync(_compare)

        assert diff == []
    finally:
        await engine.dispose()
        await _assert_url_is_actually_test_database(db_owner_url)
        subprocess.run(
            [sys.executable, "-m", "alembic", "downgrade", "base"],
            cwd=SERVICE_DIR,
            env=env,
            check=True,
        )
