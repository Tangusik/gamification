"""Точка сборки FastAPI-приложения сервиса gamification."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import (
    create_db_engine,
    create_http_client,
    create_token_denylist_reader,
    create_token_issuer,
    create_uow_factory,
    create_user_accounts,
)
from app.api.main_router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.repositories.in_memory import InMemoryStore

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Управление жизненным циклом приложения.

    Здесь рождается и умирает всё, что владеет соединениями: движок БД,
    клиент denylist users и HTTP-клиент для внутреннего выпуска токена.
    Все три обязаны закрываться на остановке.
    """
    settings = get_settings()
    logger.info("Starting service %s in %s", settings.app_name, settings.environment)

    engine = create_db_engine()
    app.state.db_engine = engine
    app.state.uow_factory = create_uow_factory(engine, InMemoryStore())
    app.state.token_denylist_reader = create_token_denylist_reader()
    app.state.http_client = create_http_client()
    app.state.token_issuer = create_token_issuer(app.state.http_client)
    app.state.user_accounts = create_user_accounts(app.state.http_client)

    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await app.state.token_denylist_reader.close()
        if engine is not None:
            await engine.dispose()
        logger.info("Stopping service %s", settings.app_name)


def create_app() -> FastAPI:
    """Собрать и вернуть приложение FastAPI.

    ``openapi_url`` — свой: ``/api/v1/openapi.json`` за шлюзом уже занят
    users (раздел 8).
    """
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(
        title=settings.app_name,
        lifespan=lifespan,
        root_path=settings.root_path,
        openapi_url="/openapi-gamification.json",
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app
