"""Пометить пакет ``tests/db`` маркером ``db`` и пропустить его без базы.

Хук, а не ``pytestmark`` в каждом модуле — тот в ``conftest.py`` не
действует, а повторять его в каждом новом файле рано или поздно забудут.
Устройство — то же, что в ``services/users/tests/db/conftest.py``.
"""

import os
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.config import get_settings

TEST_DATABASE_URL_ENV = "GAMIFICATION_TEST_DATABASE_URL"
# Второй DSN (В4/P2 плана 07a): роль-владелец, которой построена схема
# (``alembic upgrade``) — только для построения/сверки схемы, рантайм и
# сессии тестов работают под ролью приложения (``TEST_DATABASE_URL_ENV``).
TEST_OWNER_DATABASE_URL_ENV = "GAMIFICATION_TEST_OWNER_DATABASE_URL"
PACKAGE_DIR = Path(__file__).parent

# Суффикс имени тестовой базы (Т1). Инцидент 2026-09-13: прогон
# ``pytest -m db`` уничтожил dev-базу users, потому что имя базы никто не
# проверял. Разбирается через ``make_url().database``, а не подстрокой —
# иначе ``gamification_test_x`` прошла бы проверку по ошибке.
TEST_DB_NAME_SUFFIX = "_test"

# Ключи query-строки DSN, которыми asyncpg/psycopg переопределяют имя
# базы поверх пути URL (L1): ``sqlalchemy/dialects/postgresql/asyncpg.py``
# подмешивает ``url.query`` в аргументы подключения через
# ``opts.update(url.query)``, поэтому
# ``.../gamification_test?database=gamification`` проходит проверку по
# пути, а реально подключается к ``gamification``. Без учёта регистра —
# драйверы принимают параметры в любом регистре.
DATABASE_OVERRIDE_QUERY_KEYS = {"database", "dbname", "dsn", "service"}


def _require_database_url(env_var: str) -> str:
    """Общая часть Т1 для обоих DSN (В4/P2 плана 07a): разбор URL, имя базы
    оканчивается на ``_test``, query-ключи не подменяют имя базы (L1).
    """
    url = (os.environ.get(env_var) or "").strip()
    if not url:
        pytest.skip(f"{env_var} не задан: нужен поднятый docker-стек")
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
    """Вернуть DSN тестовой базы под ролью приложения или пропустить/
    остановить прогон.

    Дублирует одноимённую функцию ``tests/contract/conftest.py``
    намеренно: два независимых пакета тестов, разошедшийся импорт между
    ними обошёлся бы дороже трёх строк.
    """
    return _require_database_url(TEST_DATABASE_URL_ENV)


def require_test_owner_database_url() -> str:
    """Вернуть DSN тестовой базы под ролью-владельцем (В4/P2 плана 07a).

    Схему строит ``alembic upgrade head`` под этой ролью — у роли
    приложения нет прав DDL (У3). Без переменной пропускается так же,
    как и без основной (раздел 4 плана: «если без owner-DSN тесты должны
    пропускаться, делай это так же, как сейчас без основного DSN»).
    """
    return _require_database_url(TEST_OWNER_DATABASE_URL_ENV)


async def assert_connected_to_test_database(connection: AsyncConnection) -> None:
    """Второй рубеж Т1 (L1): имя базы проверяется на уже открытом
    соединении, а не разбором URL.

    Разбор URL (``require_test_database_url``) не видит переопределение
    имени базы через query-параметры драйвера — этот хелпер спрашивает
    саму СУБД, к чему подключение открыто на самом деле, и останавливает
    прогон перед разрушительной операцией, если это не тестовая база.
    """
    result = await connection.execute(text("SELECT current_database()"))
    actual_database = result.scalar_one() or ""
    if not actual_database.endswith(TEST_DB_NAME_SUFFIX):
        pytest.exit(
            f"Соединение фактически открыто к базе {actual_database!r}, имя "
            f"которой не оканчивается на {TEST_DB_NAME_SUFFIX!r} — отказ перед "
            "разрушительной операцией ради защиты dev-данных (L1, план 06)."
        )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    url_is_set = bool((os.environ.get(TEST_DATABASE_URL_ENV) or "").strip())
    owner_url_is_set = bool((os.environ.get(TEST_OWNER_DATABASE_URL_ENV) or "").strip())
    if not url_is_set:
        skip_reason = f"{TEST_DATABASE_URL_ENV} не задан: нужен поднятый docker-стек"
    elif not owner_url_is_set:
        # Схему строит роль-владелец (В4/P2 плана 07a) — без второго DSN
        # db-тесты не могут подготовить схему, даже если основной DSN есть.
        skip_reason = (
            f"{TEST_OWNER_DATABASE_URL_ENV} не задан: нужен поднятый docker-стек"
        )
    else:
        skip_reason = None
    skip_without_db = pytest.mark.skip(reason=skip_reason or "")
    for item in items:
        if PACKAGE_DIR not in Path(str(item.path)).parents:
            continue
        item.add_marker(pytest.mark.db)
        if skip_reason is not None:
            item.add_marker(skip_without_db)


@pytest.fixture
def db_env(service_env: None, monkeypatch: pytest.MonkeyPatch) -> str:
    """Переключить сервис на реальную БД на время одного теста.

    ``service_env`` запрашивается явно ради порядка: она выставляет
    ``memory``, эта фикстура — ``postgres`` поверх. DSN — роль приложения
    (В4/P2 плана 07a); схему строит отдельный DSN-владелец, см.
    ``db_owner_url``.
    """
    url = require_test_database_url()
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("GAMIFICATION_DATABASE_URL", url)
    get_settings.cache_clear()
    return url


@pytest.fixture
def db_owner_url() -> str:
    """DSN тестовой базы под ролью-владельцем (В4/P2 плана 07a) — только
    для построения и сверки схемы (``alembic upgrade``/``downgrade``).
    """
    return require_test_owner_database_url()


async def set_institution_context(session: AsyncSession, institution_id: UUID) -> None:
    """Выставить ``app.institution_id`` на сырой сессии db-теста (У4).

    UnitOfWork делает это сам в ``for_institution`` (В3/A1); тесты, что
    работают с адаптерами repositories/sql_alchemy.py напрямую поверх
    голой сессии, а не через UoW, обязаны выставлять контекст сами перед
    каждым запросом к RLS-таблице — переменная локальна транзакции и
    сбрасывается на ``commit()``/``rollback()``.
    """
    await session.execute(
        text("SELECT set_config('app.institution_id', :value, true)"),
        {"value": str(institution_id)},
    )
