"""Тест защиты Т1: db-тесты не должны запускаться на не-тестовой базе.

Инцидент 2026-09-13: прогон ``pytest -m db`` уничтожил dev-базу users,
потому что имя базы никто не проверял. ``require_test_database_url`` в
``tests/db/conftest.py`` и ``tests/contract/conftest.py`` останавливает
весь прогон (``pytest.exit``), если имя базы из
``GAMIFICATION_TEST_DATABASE_URL`` не оканчивается на ``_test``. Тест не
подключается к базе — только разбирает DSN, поэтому безопасен вне
докер-стека и без реальных ролей/паролей.

Второй DSN (В4/P2 плана 07a) — ``GAMIFICATION_TEST_OWNER_DATABASE_URL``,
роль-владелец, которой строится схема (``alembic upgrade``). Т1
применяется к обоим одинаково: ``require_test_owner_database_url``
проверяет то же самое над своей переменной.
"""

import pytest

import tests.contract.conftest as contract_conftest
import tests.db.conftest as db_conftest

ENV_VAR = "GAMIFICATION_TEST_DATABASE_URL"
OWNER_ENV_VAR = "GAMIFICATION_TEST_OWNER_DATABASE_URL"

# (модуль, имя проверяемой переменной, имя функции-проверки) — каждая
# пара "модуль + DSN" защищена своей функцией, а обе функции разбирают
# URL одинаково (Т1 применяется к обоим DSN, раздел 4 плана 07a).
GUARDED_TARGETS = [
    (db_conftest, ENV_VAR, "require_test_database_url"),
    (db_conftest, OWNER_ENV_VAR, "require_test_owner_database_url"),
    (contract_conftest, ENV_VAR, "require_test_database_url"),
    (contract_conftest, OWNER_ENV_VAR, "require_test_owner_database_url"),
]
TARGET_IDS = ["db-app", "db-owner", "contract-app", "contract-owner"]


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_database_not_ending_with_test_suffix(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/not_a_test_db",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_database_matching_only_by_prefix(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``gamification_test_x`` не должна проходить проверку подстрокой."""
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification_test_x",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_dev_database_named_gamification(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_database_override_via_query_string(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?database=`` в query-строке (L1): путь URL — ``_test``, но
    asyncpg/psycopg подключится по значению query-параметра, минуя
    проверку по пути (``sqlalchemy/dialects/postgresql/asyncpg.py``,
    ``opts.update(url.query)``).
    """
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification_test"
        "?database=gamification",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_dbname_override_via_query_string(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Тот же обход через ``?dbname=``, ключ psycopg (L1)."""
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification_test"
        "?dbname=users",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_rejects_database_override_regardless_of_key_case(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ключ query-параметра драйвер принимает в любом регистре (L1)."""
    monkeypatch.setenv(
        env_var,
        "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification_test"
        "?DATABASE=x",
    )
    with pytest.raises(pytest.exit.Exception):
        getattr(module, func_name)()


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_accepts_database_ending_with_test_suffix(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = "postgresql+asyncpg://gamification:pwd@127.0.0.1:5432/gamification_test"
    monkeypatch.setenv(env_var, url)
    assert getattr(module, func_name)() == url


@pytest.mark.parametrize("module,env_var,func_name", GUARDED_TARGETS, ids=TARGET_IDS)
def test_skips_when_variable_is_not_set(
    module: object, env_var: str, func_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(env_var, raising=False)
    with pytest.raises(pytest.skip.Exception):
        getattr(module, func_name)()
