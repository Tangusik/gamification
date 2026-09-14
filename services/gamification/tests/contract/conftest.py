"""Инфраструктура контрактных тестов репозиториев: оба адаптера (H1, раздел 7).

Обычный прогон получает только вариант ``in_memory``; вариант
``postgres`` помечен ``pytest.mark.db`` и требует
``GAMIFICATION_TEST_DATABASE_URL`` — без него пропускается с указанием
причины (то же устройство, что в ``services/users/tests/conftest.py``).
"""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.pool import NullPool

from app.repositories.database import create_engine, create_session_factory
from app.repositories.in_memory import (
    InMemoryInstitutionInvitations,
    InMemoryInstitutionMemberships,
    InMemoryInstitutionRepository,
    InMemoryInvitationLookup,
    InMemoryStore,
)
from app.repositories.sql_alchemy import (
    SqlAlchemyInstitutionInvitations,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
    SqlAlchemyInvitationLookup,
)
from tests.db.conftest import assert_connected_to_test_database, set_institution_context

TEST_DATABASE_URL_ENV = "GAMIFICATION_TEST_DATABASE_URL"
# Роль-владелец, которой строится схема (В4/P2 плана 07a) — см.
# ``tests/db/conftest.py``, где определена та же переменная.
TEST_OWNER_DATABASE_URL_ENV = "GAMIFICATION_TEST_OWNER_DATABASE_URL"
POSTGRES_PARAM = pytest.param("postgres", marks=pytest.mark.db)

SERVICE_DIR = Path(__file__).resolve().parents[2]

# Суффикс имени тестовой базы (Т1). Инцидент 2026-09-13: прогон
# ``pytest -m db`` уничтожил dev-базу users, потому что имя базы никто не
# проверял. Разбирается через ``make_url().database``, а не подстрокой —
# иначе ``gamification_test_x`` прошла бы проверку по ошибке.
TEST_DB_NAME_SUFFIX = "_test"

# Ключи query-строки DSN, которыми asyncpg/psycopg переопределяют имя
# базы поверх пути URL (L1) — см. тот же список в ``tests/db/conftest.py``.
DATABASE_OVERRIDE_QUERY_KEYS = {"database", "dbname", "dsn", "service"}


def _require_database_url(env_var: str) -> str:
    """Общая часть Т1 для обоих DSN контрактных тестов (В4/P2 плана 07a)."""
    url = (os.environ.get(env_var) or "").strip()
    if not url:
        pytest.skip(
            f"{env_var} не задан: тесты против реальной PostgreSQL "
            "требуют поднятого docker-стека"
        )
    parsed = make_url(url)
    query_keys = {key.lower() for key in parsed.query}
    overriding_keys = query_keys & DATABASE_OVERRIDE_QUERY_KEYS
    if overriding_keys:
        pytest.exit(
            f"{env_var} задаёт имя базы через query-параметр "
            f"{sorted(overriding_keys)!r} — драйвер подключится не туда, куда "
            "указывает путь URL, отказ ради защиты dev-данных (L1, план 06)."
        )
    database_name = parsed.database or ""
    if not database_name.endswith(TEST_DB_NAME_SUFFIX):
        pytest.exit(
            f"{env_var} указывает на базу {database_name!r}, имя которой не "
            f"оканчивается на {TEST_DB_NAME_SUFFIX!r} — отказ ради защиты "
            "dev-данных (инцидент 2026-09-13, см. план 06)."
        )
    return url


def require_test_database_url() -> str:
    """DSN тестовой базы под ролью приложения (``gamification_app``)."""
    return _require_database_url(TEST_DATABASE_URL_ENV)


def require_test_owner_database_url() -> str:
    """DSN тестовой базы под ролью-владельцем — только для ``alembic
    upgrade`` (В4/P2 плана 07a): у роли приложения нет прав DDL (У3).
    """
    return _require_database_url(TEST_OWNER_DATABASE_URL_ENV)


async def assert_app_role_is_not_owner_or_bypassrls(
    connection: AsyncConnection,
) -> None:
    """Остановить прогон, если DSN приложения на самом деле владеет
    таблицами или может обходить RLS (В5 плана 07a, риск 6).

    Без этой проверки перепутанный DSN сделал бы RLS видимым для теста,
    но бесполезным на дев-стенде: ``FORCE`` не действует на владельца, а
    политика молча не фильтрует ничего, если роль ``BYPASSRLS``.
    """
    result = await connection.execute(
        text(
            "SELECT rolsuper OR rolbypassrls AS bypasses_rls "
            "FROM pg_roles WHERE rolname = current_user"
        )
    )
    if bool(result.scalar_one()):
        pytest.exit(
            f"{TEST_DATABASE_URL_ENV} подключается суперпользователем или "
            "ролью с BYPASSRLS — RLS для неё не действует, тест RLS был бы "
            "ложно зелёным (В5 плана 07a, риск 6)."
        )
    # pg_has_role(..., 'USAGE'), а не сравнение tableowner = current_user
    # (L3): так ловится и членство в роли-владельце, не только прямое
    # совпадение имени роли.
    owned_tables = await connection.execute(
        text(
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname = 'public' "
            "AND pg_has_role(current_user, tableowner, 'USAGE')"
        )
    )
    if owned_tables.scalar_one() > 0:
        pytest.exit(
            f"{TEST_DATABASE_URL_ENV} подключается ролью-владельцем таблиц "
            "(прямо или через членство) — FORCE ROW LEVEL SECURITY на "
            "владельца не действует, тест RLS был бы ложно зелёным (В5 "
            "плана 07a, риск 6)."
        )


def _run_alembic_upgrade_head(*, owner_database_url: str) -> None:
    """Выполнить ``alembic upgrade head`` под ролью-владельцем.

    Подпроцесс, а не вызов ``alembic.command`` в процессе: тот же приём,
    что и в ``tests/db/test_migration_matches_models.py`` — изолирует
    состояние alembic между вызовами в одном тестовом прогоне.
    """
    env = dict(os.environ)
    env["GAMIFICATION_DATABASE_URL"] = owner_database_url
    env["GAMIFICATION_STORAGE_BACKEND"] = "postgres"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=SERVICE_DIR,
        env=env,
        check=True,
    )


@asynccontextmanager
async def postgres_schema(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Пересоздать схему в тестовой базе миграцией и отдать движок поверх
    неё (В4/P2 плана 07a).

    Источник схемы — ``alembic upgrade head`` под ролью-владельцем
    (``GAMIFICATION_TEST_OWNER_DATABASE_URL``): у роли приложения нет
    прав DDL (У3), а дублировать SQL политик/GRANT/триггера в фикстуре
    (P1) значит держать копию, расхождение с которой никто не проверяет
    (риск 9 плана). ``database_url`` — DSN приложения, под которым
    работают сами тесты и который возвращает эта функция. Схема
    пересоздаётся с нуля (``DROP SCHEMA public CASCADE``) в начале
    каждого вызова — предыдущий прогон её не убирает, следующий вызов
    убирает сам, поэтому лишний ``alembic downgrade`` на выходе не нужен.
    """
    owner_url = require_test_owner_database_url()
    owner_engine = create_engine(owner_url, poolclass=NullPool)
    try:
        async with owner_engine.connect() as connection:
            # Второй рубеж Т1 (L1) — на обоих DSN: по факту открытого
            # соединения, не по разбору URL.
            await assert_connected_to_test_database(connection)
        async with owner_engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await owner_engine.dispose()

    _run_alembic_upgrade_head(owner_database_url=owner_url)

    app_engine = create_engine(database_url, poolclass=NullPool)
    try:
        async with app_engine.connect() as connection:
            await assert_connected_to_test_database(connection)
            await assert_app_role_is_not_owner_or_bypassrls(connection)
        yield app_engine
    finally:
        await app_engine.dispose()


@pytest.fixture(params=["in_memory", POSTGRES_PARAM])
async def repos(request: pytest.FixtureRequest):
    """``(institution_repo, membership_repo_for)`` на общем хранилище.

    ``membership_repo_for`` асинхронна в обоих вариантах (У3-У5 плана
    07a): под ``[postgres]`` она выставляет ``app.institution_id`` перед
    тем, как отдать репозиторий, иначе ``FORCE ROW LEVEL SECURITY`` даёт
    0 строк на чтении и падение ``WITH CHECK`` на записи. В ``in_memory``
    выставлять нечего, но сигнатура остаётся одинаковой, чтобы тест не
    знал, под каким вариантом он выполняется.
    """
    if request.param == "in_memory":
        store = InMemoryStore()
        institution_repo = InMemoryInstitutionRepository(store)

        async def membership_repo_for(institution_id):
            return InMemoryInstitutionMemberships(store, institution_id)

        yield institution_repo, membership_repo_for
        return

    async with postgres_schema(require_test_database_url()) as engine:
        async with create_session_factory(engine)() as session:
            institution_repo = SqlAlchemyInstitutionRepository(session)

            async def membership_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyInstitutionMemberships(session, institution_id)

            yield institution_repo, membership_repo_for


@pytest.fixture(params=["in_memory", POSTGRES_PARAM])
async def invitation_repos(request: pytest.FixtureRequest):
    """``(institution_repo, invitation_repo_for, invitation_lookup)`` (раздел 4, H1).

    ``invitation_repo_for`` асинхронна и под ``[postgres]`` выставляет
    контекст учреждения, как и ``membership_repo_for`` выше. ``lookup``
    контекста не требует: ``get_for_accept``/``increment_uses`` работают
    через свою переменную ``app.invitation_token`` (В1/X1) или через
    контекст, уже выставленный предыдущим вызовом ``invitation_repo_for``
    в этой же транзакции, — выставлять его здесь ещё раз означало бы
    маскировать межарендную политику под обычную.
    """
    if request.param == "in_memory":
        store = InMemoryStore()
        institution_repo = InMemoryInstitutionRepository(store)

        async def invitation_repo_for(institution_id):
            return InMemoryInstitutionInvitations(store, institution_id)

        yield institution_repo, invitation_repo_for, InMemoryInvitationLookup(store)
        return

    async with postgres_schema(require_test_database_url()) as engine:
        async with create_session_factory(engine)() as session:
            institution_repo = SqlAlchemyInstitutionRepository(session)

            async def invitation_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyInstitutionInvitations(session, institution_id)

            yield (
                institution_repo,
                invitation_repo_for,
                SqlAlchemyInvitationLookup(session),
            )
