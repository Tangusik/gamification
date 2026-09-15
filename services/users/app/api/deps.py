"""Зависимости HTTP-слоя сервиса users.

Модуль — единственная точка подмены хранилища. Кроме пакета
``app.repositories``, только здесь допускается упоминание конкретной
реализации: остальной код видит лишь псевдонимы ``UserRepository`` и
``TokenDenylist``.

Ветвление по ``settings.storage_backend`` живёт в ``create_db_engine``,
``create_user_storage``, ``session_scope`` и ``build_user_db`` — и
больше нигде. Выбор реализации denylist — в ``create_token_denylist``.
"""

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.auth.user_manager import UserManager
from app.clients.gamification_memberships import GamificationMembershipsClient
from app.core.config import get_settings
from app.repositories.database import create_engine, create_session_factory
from app.repositories.denylist import (
    InMemoryTokenDenylist,
    RedisTokenDenylist,
    TokenDenylist,
    create_redis_client,
)
from app.repositories.in_memory import (
    InMemoryRefreshSessionRepository,
    InMemoryUserDatabase,
)
from app.repositories.memory_store import InMemoryRefreshSessionStore, InMemoryUserStore
from app.repositories.protocols import RefreshSessionRepository, UserRepository
from app.repositories.sql_alchemy import (
    SqlAlchemyRefreshSessionRepository,
    SqlAlchemyUserRepository,
)

# Таймаут HTTP-вызова в gamification (раздел 4.6 плана 03, тот же, что у
# gamification → users): ретраев здесь нет, повтор со стороны клиента
# безопасен, а долгий таймаут превратил бы «недоступна» в подвисший запрос.
GAMIFICATION_HTTP_TIMEOUT_SECONDS = 2.0

logger = logging.getLogger(__name__)

# Владелец данных и их времени жизни: фабрика сессий на PostgreSQL,
# словари в памяти — в режиме ``memory``. Лежит в ``app.state``, а не в
# модульной переменной, поэтому каждый ``create_app()`` изолирован.
UserStorage = InMemoryUserStore | async_sessionmaker[AsyncSession]

# Сессия одного запроса. В памяти роль сессии играет само хранилище:
# отдельного объекта транзакции там нет.
Session = InMemoryUserStore | AsyncSession


def create_db_engine() -> AsyncEngine | None:
    """ШОВ: движок БД приложения либо ``None`` в режиме ``memory``.

    Вызывается один раз на приложение (в ``lifespan``) и складывается в
    ``app.state.db_engine``: движок владеет пулом соединений, и его
    обязан закрыть тот же ``lifespan`` через ``await engine.dispose()``.

    Отдельная функция, а не создание движка внутри
    ``create_user_storage``, нужна именно ради закрытия: из фабрики
    сессий движок доставать пришлось бы через её внутренности.
    """
    settings = get_settings()
    if settings.storage_backend == "memory":
        return None
    return create_engine((settings.database_url or "").strip(), pool_pre_ping=True)


def create_user_storage(engine: AsyncEngine | None) -> UserStorage:
    """ШОВ: создание хранилища приложения поверх движка.

    ``engine is None`` означает режим ``memory`` — единственная ветка,
    где данные живут в процессе и теряются при рестарте. Настройки
    здесь повторно не читаются: решение уже принято в
    ``create_db_engine``, и два независимых чтения разъехались бы.
    """
    if engine is None:
        return InMemoryUserStore()
    return create_session_factory(engine)


@asynccontextmanager
async def session_scope(storage: UserStorage) -> AsyncIterator[Session]:
    """ШОВ: жизненный цикл одной сессии поверх хранилища.

    Вынесено из ``get_session`` отдельно, потому что сессия нужна не
    только запросу: сид bootstrap-админа выполняется в ``lifespan``, где
    зависимостей FastAPI нет, а открывать её вторым способом — значит
    завести второе место ветвления.
    """
    if isinstance(storage, InMemoryUserStore):
        yield storage
        return
    async with storage() as session:
        yield session


async def get_session(request: Request) -> AsyncGenerator[Session]:
    """ШОВ: сессия запроса, общая для репозиториев пользователя.

    Единственность обеспечивается кешем зависимостей FastAPI в пределах
    запроса: провайдер ниже зависит от этой функции, поэтому получает
    тот же объект, что и любой другой потребитель сессии в том же
    запросе.
    """
    async with session_scope(request.app.state.user_storage) as session:
        yield session


def build_user_db(session: Session) -> UserRepository:
    """ШОВ: сборка адаптера пользователей поверх сессии.

    Прикладной код зависит от возвращаемого типа ``UserRepository``,
    поэтому выбор реализации его не затрагивает.
    """
    if isinstance(session, InMemoryUserStore):
        return InMemoryUserDatabase(session)
    return SqlAlchemyUserRepository(session)


def create_refresh_session_storage(
    engine: AsyncEngine | None,
) -> InMemoryRefreshSessionStore | None:
    """ШОВ: хранилище refresh-сессий в режиме ``memory``, иначе ``None``.

    В режиме PostgreSQL отдельного объекта не заводится — репозиторий
    строится прямо поверх сессии запроса, как и у пользователей.
    """
    if engine is None:
        return InMemoryRefreshSessionStore()
    return None


def build_refresh_session_repository(
    session: Session, refresh_storage: InMemoryRefreshSessionStore | None
) -> RefreshSessionRepository:
    """ШОВ: сборка адаптера refresh-сессий поверх сессии.

    ``refresh_storage`` заполнен только в режиме ``memory``: там сессия
    запроса — это глобальное хранилище пользователей, но состояние
    refresh-сессий живёт отдельно (своя блокировка на сессию), поэтому
    приходит вторым параметром, а не выводится из ``session``.
    """
    if isinstance(session, InMemoryUserStore):
        assert refresh_storage is not None, (
            "InMemoryRefreshSessionStore is required when storage_backend=memory"
        )
        return InMemoryRefreshSessionRepository(refresh_storage)
    return SqlAlchemyRefreshSessionRepository(session)


async def get_refresh_session_repository(
    session: Annotated[Session, Depends(get_session)],
    request: Request,
) -> RefreshSessionRepository:
    """ШОВ: провайдер хранилища refresh-сессий для обработчиков запросов."""
    return build_refresh_session_repository(
        session, request.app.state.refresh_session_storage
    )


def create_http_client() -> httpx.AsyncClient:
    """ШОВ: единственный HTTP-клиент приложения, таймаут 2 с.

    По образцу ``create_http_client`` сервиса gamification — тот же
    подход к единственному клиенту на приложение и тому же таймауту.
    """
    return httpx.AsyncClient(timeout=GAMIFICATION_HTTP_TIMEOUT_SECONDS)


def create_memberships_client(
    client: httpx.AsyncClient,
) -> GamificationMembershipsClient:
    """ШОВ: адаптер проверки членства в gamification (вопрос 1 = А)."""
    settings = get_settings()
    return GamificationMembershipsClient(
        client,
        base_url=(settings.gamification_internal_url or "").strip(),
        service_secret=settings.gamification_service_secret.get_secret_value(),
    )


async def get_memberships_client(request: Request) -> GamificationMembershipsClient:
    """ШОВ: провайдер клиента gamification для обработчиков запросов."""
    return request.app.state.memberships_client


def create_token_denylist() -> TokenDenylist:
    """ШОВ: создание denylist отозванных токенов.

    Выбор по ``USERS_REDIS_URL``: задан — Redis, не задан — реализация в
    памяти. Пустой URL вне ``local``/``test`` роняет старт (проверка в
    ``app.core.config``) — симметрично правилу для хранилища: в проде
    denylist, живущий в процессе, означает, что отзыв не работает на
    второй реплике.

    Клиент создаётся один на приложение и кладётся в
    ``app.state.token_denylist``: он владеет пулом соединений, закрыть
    его обязан ``lifespan``.
    """
    settings = get_settings()
    url = (settings.redis_url or "").strip()
    if not url:
        return InMemoryTokenDenylist()
    return RedisTokenDenylist(create_redis_client(url))


async def get_token_denylist(request: Request) -> TokenDenylist:
    """ШОВ: провайдер denylist для стратегии и проб готовности."""
    denylist: TokenDenylist = request.app.state.token_denylist
    return denylist


async def probe_database(app: FastAPI) -> bool:
    """Проверить, отвечает ли хранилище: ``SELECT 1`` в отдельной сессии.

    В режиме ``memory`` проверять нечего: хранилище — часть процесса, и
    если процесс отвечает, то отвечает и оно.

    Исключение ловится широко намеренно: недоступность БД приходит и
    ``SQLAlchemyError``, и ошибками сокета из драйвера, а readiness
    обязана отвечать 503, а не 500.
    """
    storage: UserStorage = app.state.user_storage
    if isinstance(storage, InMemoryUserStore):
        return True
    try:
        async with session_scope(storage) as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness probe: database is unavailable")
        return False
    return True


async def probe_denylist(app: FastAPI) -> bool:
    """Проверить, отвечает ли denylist отозванных токенов.

    Недоступность отражается в readiness, но не отвергает запросы:
    проверка denylist работает fail-open (см. ``app.auth.strategy``).
    """
    denylist: TokenDenylist = app.state.token_denylist
    return await denylist.ping()


async def get_user_db(
    session: Annotated[Session, Depends(get_session)],
) -> AsyncGenerator[UserRepository]:
    """ШОВ: провайдер хранилища пользователей для обработчиков запросов."""
    yield build_user_db(session)


async def get_user_manager(
    user_db: Annotated[UserRepository, Depends(get_user_db)],
    refresh_sessions: Annotated[
        RefreshSessionRepository, Depends(get_refresh_session_repository)
    ],
) -> AsyncGenerator[UserManager]:
    """Провайдер прикладного менеджера пользователей.

    Менеджер получает хранилище по псевдониму ``UserRepository``, поэтому
    смена реализации хранилища его не затрагивает. ``refresh_sessions``
    нужен, чтобы смена пароля могла погасить все сессии пользователя
    (вопрос 5, план 10-refresh).
    """
    yield UserManager(user_db, refresh_sessions)
