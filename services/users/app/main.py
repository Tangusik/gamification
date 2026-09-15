"""Точка сборки FastAPI-приложения сервиса users."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import (
    build_user_db,
    create_db_engine,
    create_http_client,
    create_memberships_client,
    create_refresh_session_storage,
    create_token_denylist,
    create_user_storage,
    session_scope,
)
from app.api.main_router import api_router
from app.auth.bootstrap import seed_bootstrap_admin
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения.

    Здесь рождается и умирает всё, что владеет соединениями: движок БД с
    его пулом и клиент denylist. Оба обязаны закрываться на остановке —
    иначе при рестарте в тестах и при перезапуске воркера соединения
    утекают, а событийный цикл закрывается с предупреждениями.

    Фоновых задач нет, поэтому завершение по SIGTERM происходит сразу.
    """
    settings = get_settings()
    logger.info("Starting service %s in %s", settings.app_name, settings.environment)
    engine = create_db_engine()
    app.state.db_engine = engine
    app.state.user_storage = create_user_storage(engine)
    app.state.refresh_session_storage = create_refresh_session_storage(engine)
    app.state.token_denylist = create_token_denylist()
    app.state.http_client = create_http_client()
    app.state.memberships_client = create_memberships_client(app.state.http_client)

    try:
        # Сид выполняется только при явно заданных настройках: учётка с
        # предсказуемым паролем по умолчанию недопустима.
        admin_email = (settings.bootstrap_admin_email or "").strip()
        admin_password = (
            settings.bootstrap_admin_password.get_secret_value()
            if settings.bootstrap_admin_password is not None
            else ""
        ).strip()
        if admin_email and admin_password:
            # Сессия открывается явно и закрывается вместе с блоком:
            # запроса здесь нет, значит нет и зависимости, которая
            # сделала бы это за нас.
            async with session_scope(app.state.user_storage) as session:
                await seed_bootstrap_admin(
                    build_user_db(session), admin_email, admin_password
                )

        yield
    finally:
        await app.state.http_client.aclose()
        await app.state.token_denylist.close()
        if engine is not None:
            await engine.dispose()
        logger.info("Stopping service %s", settings.app_name)


def create_app() -> FastAPI:
    """Собрать и вернуть приложение FastAPI."""
    settings = get_settings()
    configure_logging(settings.log_level)

    # root_path не префиксует маршруты — сервис отвечает по тем же
    # путям, что и без него. Он лишь сообщает FastAPI, под каким
    # префиксом сервис виден снаружи, чтобы OpenAPI и /docs указывали
    # адреса, по которым клиент реально ходит через шлюз.
    app = FastAPI(
        title=settings.app_name, lifespan=lifespan, root_path=settings.root_path
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app
