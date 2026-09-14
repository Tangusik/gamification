"""Перевод дедлока/serialization failure в доменную ошибку (решение
владельца от 2026-09-14).

Не-db часть: без реальной PostgreSQL, на сконструированных
``DBAPIError`` — ``40P01`` и ``40001`` переводятся в
``ConcurrentUpdateError`` в единой точке перехвата
(``SqlAlchemyUnitOfWork.__aexit__``), посторонний SQLSTATE — нет.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.business.domain.errors import ConcurrentUpdateError
from app.repositories.sql_alchemy import concurrent_update_sqlstate
from app.repositories.uow import SqlAlchemyUnitOfWork


class _FakeOrigError(Exception):
    """Заглушка под исключение драйвера с атрибутом ``sqlstate``."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _dbapi_error(sqlstate: str, *, on_cause: bool = False) -> DBAPIError:
    if on_cause:
        # asyncpg иногда кладёт диагностику на исходное исключение в
        # ``__cause__`` (см. ``_violated_constraint_name`` в
        # ``app/repositories/sql_alchemy.py``), а не прямо на ``orig``.
        orig = Exception("wrapped")
        orig.__cause__ = _FakeOrigError(sqlstate)
    else:
        orig = _FakeOrigError(sqlstate)
    return DBAPIError("SELECT 1", {}, orig)


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
def test_concurrent_update_sqlstate_detects_orig(sqlstate: str) -> None:
    error = _dbapi_error(sqlstate)
    assert concurrent_update_sqlstate(error) == sqlstate


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
def test_concurrent_update_sqlstate_detects_cause(sqlstate: str) -> None:
    error = _dbapi_error(sqlstate, on_cause=True)
    assert concurrent_update_sqlstate(error) == sqlstate


def test_concurrent_update_sqlstate_ignores_other_codes() -> None:
    error = _dbapi_error("23505")
    assert concurrent_update_sqlstate(error) is None


def test_concurrent_update_sqlstate_ignores_non_dbapi_errors() -> None:
    assert concurrent_update_sqlstate(ValueError("boom")) is None


def _fake_session_factory(session: AsyncMock):
    return lambda: session


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
async def test_uow_translates_deadlock_to_domain_error(sqlstate: str) -> None:
    session = AsyncMock()
    uow = SqlAlchemyUnitOfWork(_fake_session_factory(session))

    with pytest.raises(ConcurrentUpdateError):
        async with uow:
            raise _dbapi_error(sqlstate)

    session.rollback.assert_awaited_once()
    session.close.assert_awaited_once()


async def test_uow_does_not_translate_other_integrity_errors() -> None:
    session = AsyncMock()
    uow = SqlAlchemyUnitOfWork(_fake_session_factory(session))

    original = IntegrityError("INSERT", {}, _FakeOrigError("23505"))
    with pytest.raises(IntegrityError):
        async with uow:
            raise original


async def test_uow_translates_deadlock_on_commit() -> None:
    """Дедлок на явном ``commit()`` внутри ``async with`` тоже перехватывается."""
    session = AsyncMock()
    session.commit.side_effect = _dbapi_error("40P01")
    uow = SqlAlchemyUnitOfWork(_fake_session_factory(session))

    with pytest.raises(ConcurrentUpdateError):
        async with uow as scope:
            await scope.commit()
