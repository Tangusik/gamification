"""Инфраструктура SQLAlchemy: декларативная база и фабрики движка.

Схема идентична ``services/users/app/repositories/database.py``: то же
соглашение имён (нужно alembic'у для автогенерации ``drop_constraint``)
и тот же принцип — URL приходит аргументом, настройки здесь не читаются.
"""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Общая декларативная база всех моделей сервиса.

    ``metadata`` этого класса — то, что видит alembic как целевую схему
    (``target_metadata`` в ``alembic/env.py``).
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(database_url: str, **kwargs: object) -> AsyncEngine:
    """Создать асинхронный движок для указанного DSN.

    ``hide_parameters=True`` по умолчанию: приглашение хранится открытым
    текстом (F5) и передаётся параметром в ``SELECT ... FOR UPDATE`` и
    ``INSERT`` (use case принятия приглашения). При ``DBAPIError`` текст
    ошибки по умолчанию содержит ``[parameters: (...)]``, и токен уходит в
    лог uvicorn. ``setdefault`` оставляет возможность переопределить
    значение явным аргументом там, где это осознанно нужно.
    """
    kwargs.setdefault("hide_parameters", True)
    return create_async_engine(database_url, **kwargs)  # type: ignore[arg-type]


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создать фабрику сессий поверх готового движка.

    ``expire_on_commit=False`` обязателен: иначе первое обращение к
    атрибуту объекта после ``commit`` вне ``await`` даёт
    ``MissingGreenlet`` в самом неожиданном месте.
    """
    return async_sessionmaker(engine, expire_on_commit=False)
