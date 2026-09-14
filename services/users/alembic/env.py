"""Окружение alembic сервиса users.

Async-вариант: движок тот же, что в рантайме (``postgresql+asyncpg``),
поэтому миграции и сервис не расходятся в диалекте.

Адрес базы берётся из ``Settings``, а не из ``alembic.ini``:
конфигурация сервиса идёт только через переменные окружения
(``knowledge/03-architecture.md``), а DSN содержит пароль. Следствие,
о котором стоит знать: ``Settings`` требует и ключи подписи, поэтому
шаг миграций запускается с тем же набором переменных, что и сам сервис
(в compose это общий якорь ``x-users-env``).
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection

from alembic import context
from app.core.config import get_settings
from app.repositories.database import Base, create_engine

# Импорт моделей нужен ради побочного эффекта: без него таблицы не
# зарегистрируются в ``Base.metadata`` и autogenerate решит, что схема
# пуста, а значит сгенерирует удаление всех таблиц.
from app.repositories import models  # noqa: F401  isort:skip

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """Вернуть DSN из настроек сервиса.

    ``storage_backend=memory`` мигрировать нечего, и молча ничего не
    делать здесь опаснее, чем упасть: в CI это выглядело бы как
    успешный шаг миграций на пустой базе.
    """
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "USERS_DATABASE_URL is required to run migrations "
            "(USERS_STORAGE_BACKEND must be 'postgres')"
        )
    return settings.database_url


def run_migrations_offline() -> None:
    """Сгенерировать SQL без подключения к базе (``alembic --sql``)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Выполнить миграции на уже открытом соединении."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Открыть async-соединение и прогнать миграции внутри него.

    ``NullPool``: процесс миграций живёт один прогон, пул соединений ему
    не нужен и только мешал бы корректному завершению.
    """
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Точка входа онлайн-режима."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
