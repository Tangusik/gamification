"""Зависимости HTTP-слоя: сборка адаптеров и use case'ов (шов).

Единственная точка, где business-порты связываются с конкретными
реализациями (``app.repositories``, ``app.clients``, ``app.auth``).
Прикладной код (обработчики в ``app/api/external``) видит только
псевдонимы портов из ``app.business.ports``.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.auth.denylist import (
    NullTokenDenylistReader,
    RedisTokenDenylistReader,
    TokenDenylistReader,
    create_redis_client,
)
from app.business.ports import Clock, TokenIssuer, UnitOfWork, UserAccounts
from app.business.use_cases.context import SwitchInstitution
from app.business.use_cases.currency import (
    CreateAccrual,
    CreateReversal,
    GetMyCurrency,
    GetStudentCurrency,
)
from app.business.use_cases.groups import (
    AddGroupStudent,
    AddGroupTeacher,
    CreateGroup,
    DeleteGroup,
    ListGroups,
    RemoveGroupStudent,
    RemoveGroupTeacher,
    UpdateGroup,
)
from app.business.use_cases.institution_settings import (
    GetInstitution,
    UpdateInstitution,
)
from app.business.use_cases.institutions import CreateInstitution, ListMyInstitutions
from app.business.use_cases.invitations import (
    AcceptInvitation,
    CreateInvitation,
    ListInvitations,
    RevokeInvitation,
)
from app.business.use_cases.market import (
    CreatePrivilege,
    CreatePurchase,
    FulfilPurchase,
    ListMyPurchases,
    ListPrivileges,
    ListPurchases,
    RejectPurchase,
    UpdatePrivilege,
)
from app.business.use_cases.students import ListStudents, UpdateStudent
from app.business.use_cases.teachers import CreateTeacher, ListTeachers, UpdateTeacher
from app.clients.users_accounts import UsersAccounts
from app.clients.users_tokens import UsersTokenIssuer
from app.core.config import get_settings
from app.repositories.database import create_engine, create_session_factory
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork, SqlAlchemyUnitOfWork

logger = logging.getLogger(__name__)

# Одна фабрика на приложение — создаёт свежий UnitOfWork на каждый запрос.
UnitOfWorkFactory = Callable[[], UnitOfWork]


class SystemClock:
    """Часы приложения — единственная точка, откуда бизнес-слой берёт время."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def create_db_engine() -> AsyncEngine | None:
    """ШОВ: движок БД приложения либо ``None`` в режиме ``memory``.

    Вызывается один раз в ``lifespan``; движок владеет пулом соединений
    и обязан быть закрыт там же (``await engine.dispose()``).
    """
    settings = get_settings()
    if settings.storage_backend == "memory":
        return None
    return create_engine((settings.database_url or "").strip())


def create_uow_factory(
    engine: AsyncEngine | None, memory_store: InMemoryStore
) -> UnitOfWorkFactory:
    """ШОВ: фабрика ``UnitOfWork`` — новый экземпляр на каждый запрос."""
    if engine is None:

        def _memory_factory() -> UnitOfWork:
            return InMemoryUnitOfWork(memory_store)

        return _memory_factory

    session_factory = create_session_factory(engine)

    def _sql_factory() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(session_factory)

    return _sql_factory


def create_token_denylist_reader() -> TokenDenylistReader:
    """ШОВ: выбор чтения denylist по ``GAMIFICATION_REDIS_URL`` (K1)."""
    settings = get_settings()
    url = (settings.redis_url or "").strip()
    if not url:
        return NullTokenDenylistReader()
    return RedisTokenDenylistReader(create_redis_client(url))


def create_http_client() -> httpx.AsyncClient:
    """ШОВ: единственный HTTP-клиент приложения, таймаут 2 с (раздел 4.6)."""
    return httpx.AsyncClient(timeout=2.0)


def create_token_issuer(client: httpx.AsyncClient) -> TokenIssuer:
    """ШОВ: адаптер внутреннего выпуска токена users."""
    settings = get_settings()
    return UsersTokenIssuer(
        client,
        base_url=settings.users_internal_url,
        service_secret=settings.users_service_secret.get_secret_value(),
    )


def create_user_accounts(client: httpx.AsyncClient) -> UserAccounts:
    """ШОВ: адаптер внутреннего создания аккаунта в users (В1/А1)."""
    settings = get_settings()
    return UsersAccounts(
        client,
        base_url=settings.users_internal_url,
        service_secret=settings.users_service_secret.get_secret_value(),
    )


async def get_uow(request: Request) -> UnitOfWork:
    """ШОВ: новый Unit of Work на запрос."""
    factory: UnitOfWorkFactory = request.app.state.uow_factory
    return factory()


async def get_clock() -> Clock:
    return SystemClock()


async def get_token_issuer(request: Request) -> TokenIssuer:
    return request.app.state.token_issuer


async def get_user_accounts(request: Request) -> UserAccounts:
    return request.app.state.user_accounts


async def get_create_institution(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreateInstitution:
    return CreateInstitution(uow, clock)


async def get_list_my_institutions(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListMyInstitutions:
    return ListMyInstitutions(uow)


async def get_switch_institution(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    token_issuer: Annotated[TokenIssuer, Depends(get_token_issuer)],
) -> SwitchInstitution:
    return SwitchInstitution(uow, token_issuer)


async def get_create_invitation(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreateInvitation:
    return CreateInvitation(uow, clock)


async def get_list_invitations(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListInvitations:
    return ListInvitations(uow)


async def get_revoke_invitation(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> RevokeInvitation:
    return RevokeInvitation(uow)


async def get_accept_invitation(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AcceptInvitation:
    return AcceptInvitation(uow, clock)


async def get_create_teacher(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
    user_accounts: Annotated[UserAccounts, Depends(get_user_accounts)],
) -> CreateTeacher:
    return CreateTeacher(uow, clock, user_accounts)


async def get_list_teachers(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListTeachers:
    return ListTeachers(uow)


async def get_update_teacher(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> UpdateTeacher:
    return UpdateTeacher(uow)


async def get_list_students(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListStudents:
    return ListStudents(uow)


async def get_update_student(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> UpdateStudent:
    return UpdateStudent(uow)


async def get_create_group(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreateGroup:
    return CreateGroup(uow, clock)


async def get_list_groups(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListGroups:
    return ListGroups(uow)


async def get_update_group(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> UpdateGroup:
    return UpdateGroup(uow)


async def get_delete_group(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> DeleteGroup:
    return DeleteGroup(uow)


async def get_add_group_teacher(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> AddGroupTeacher:
    return AddGroupTeacher(uow)


async def get_remove_group_teacher(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> RemoveGroupTeacher:
    return RemoveGroupTeacher(uow)


async def get_add_group_student(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> AddGroupStudent:
    return AddGroupStudent(uow)


async def get_remove_group_student(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> RemoveGroupStudent:
    return RemoveGroupStudent(uow)


async def get_get_my_currency(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> GetMyCurrency:
    return GetMyCurrency(uow)


async def get_get_student_currency(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> GetStudentCurrency:
    return GetStudentCurrency(uow)


async def get_create_accrual(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreateAccrual:
    return CreateAccrual(uow, clock)


async def get_create_reversal(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreateReversal:
    return CreateReversal(uow, clock)


async def get_list_privileges(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListPrivileges:
    return ListPrivileges(uow)


async def get_create_privilege(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreatePrivilege:
    return CreatePrivilege(uow, clock)


async def get_update_privilege(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> UpdatePrivilege:
    return UpdatePrivilege(uow, clock)


async def get_create_purchase(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> CreatePurchase:
    return CreatePurchase(uow, clock)


async def get_list_my_purchases(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListMyPurchases:
    return ListMyPurchases(uow)


async def get_list_purchases(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> ListPurchases:
    return ListPurchases(uow)


async def get_fulfil_purchase(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> FulfilPurchase:
    return FulfilPurchase(uow, clock)


async def get_reject_purchase(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> RejectPurchase:
    return RejectPurchase(uow, clock)


async def get_get_institution(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> GetInstitution:
    return GetInstitution(uow)


async def get_update_institution(
    uow: Annotated[UnitOfWork, Depends(get_uow)],
) -> UpdateInstitution:
    return UpdateInstitution(uow)


async def probe_database(app: FastAPI) -> bool:
    """Проверить, отвечает ли хранилище: ``SELECT 1`` в отдельном соединении.

    В режиме ``memory`` проверять нечего — хранилище часть процесса.
    """
    engine: AsyncEngine | None = app.state.db_engine
    if engine is None:
        return True
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness probe: database is unavailable")
        return False
    return True


async def probe_denylist(app: FastAPI) -> bool:
    """Проверить, отвечает ли denylist users.

    Недоступность отражается в readiness, но не отвергает запросы (K1):
    проверка работает fail-open.
    """
    reader: TokenDenylistReader = app.state.token_denylist_reader
    return await reader.ping()
