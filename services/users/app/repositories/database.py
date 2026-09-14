"""Инфраструктура SQLAlchemy: декларативная база и фабрики движка.

Модуль лежит внутри ``app.repositories`` — единственного пакета,
которому разрешено знать конкретную реализацию хранилища (плюс
``app.api.deps``, где собирается шов). Прикладной код сюда не смотрит.

Здесь нет ни одного обращения к настройкам: URL приходит аргументом.
Так один и тот же код собирает движок и в рантайме сервиса, и в
миграциях, и в тестах — каждый со своим источником URL.
"""

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Шаблоны имён ограничений и индексов. Задаются с первой миграции и
# больше не меняются: alembic умеет автогенерировать удаление
# ограничения, только если способен вывести его имя из модели. Без
# convention имена придумывает сама БД, и первая же попытка
# сгенерировать ``drop_constraint`` в следующей миграции упирается в
# ``NoneType`` — лечится это уже руками и по всем таблицам сразу.
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

    ``kwargs`` пробрасываются в ``create_async_engine`` без обработки:
    тестам нужен ``poolclass=NullPool``, чтобы пул не пережил
    событийный цикл функциональной фикстуры, а рантайму — параметры
    пула. Знание об этом остаётся у вызывающего.
    """
    return create_async_engine(database_url, **kwargs)  # type: ignore[arg-type]


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Создать фабрику сессий поверх готового движка.

    ``expire_on_commit=False`` обязателен, а не вкусовой: с дефолтным
    ``True`` объекты после ``commit`` помечаются просроченными, и первое
    же обращение к атрибуту вне ``await`` пытается выполнить
    синхронный SELECT — в async-мире это ``MissingGreenlet``, причём в
    самом неожиданном месте (например, при сериализации ответа).
    """
    return async_sessionmaker(engine, expire_on_commit=False)
