"""Внутреннее API gamification — вызовы от других микросервисов.

Эндпоинты:

- ``POST /memberships/resolve`` (план `.claude/plans/10-refresh.md`,
  Ч2): им пользуется users при refresh, чтобы восстановить контекст
  учреждения, переданный клиентом в теле запроса, без выдачи прав,
  которых у пользователя уже нет.
- ``PATCH /memberships/profile-name`` (план `.claude/plans/11-user-name.md`,
  этап 3): им пользуется users, когда меняется имя в профиле —
  gamification обновляет кэш-копию (``profile_name``) во всех
  членствах пользователя сразу, по всем учреждениям.

Роутер лежит вне ``/institutions`` и потому недостижим снаружи по
построению (``.claude/knowledge/07-routing.md``), а не по запрету в
nginx; подключается с ``include_in_schema=False``
(``app/api/main_router.py``).

Аутентификация вызывающего — собственный служебный секрет
(``X-Service-Secret``), симметрично тому, как gamification
аутентифицируется перед users (C1,
``services/users/app/api/internal/internal_router.py``). Секрет
обратного направления не совпадает с тем, которым gamification ходит в
users (У7 плана): утечка одного не должна давать выдать себя за оба
сервиса разом.
"""

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_resolve_membership, get_sync_profile_name
from app.business.domain.internal_errors import ServiceAuthFailedError
from app.business.use_cases.context import MembershipResolution, ResolveMembership
from app.business.use_cases.profile_names import ProfileNameSyncResult, SyncProfileName
from app.core.config import get_settings

# Профильное имя до 100 символов — тот же лимит, что у
# ``memberships.profile_name`` (миграция ``0007``).
PROFILE_NAME_MAX_LENGTH = 100


class MembershipResolveRequest(BaseModel):
    """Тело запроса на разрешение членства.

    ``extra="forbid"``: лишнее поле в теле служебного вызова — признак
    рассинхронизации контракта, а не то, что можно молча проигнорировать.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    institution_id: uuid.UUID


class MembershipResolveResponse(BaseModel):
    """Ответ на успешное разрешение — только роль."""

    role: str


class ProfileNameSyncRequest(BaseModel):
    """Тело запроса синхронизации профильного имени (план 11, этап 3).

    ``extra="forbid"`` — тем же приёмом, что у ``MembershipResolveRequest``.
    ``full_name=None`` допустим — это сброс имени в профиле.
    """

    model_config = ConfigDict(extra="forbid")

    user_id: uuid.UUID
    full_name: str | None = Field(default=None, max_length=PROFILE_NAME_MAX_LENGTH)


class ProfileNameSyncResponse(BaseModel):
    """Ответ синхронизации — число обновлённых членств.

    Пользователь без членств — 200 с ``updated=0``, а не ошибка (план
    11): имя в профиле меняют и те, кто ни в одном учреждении не
    состоит.
    """

    updated: int


def _service_secret_matches(provided: str, secret: str) -> bool:
    """Сравнить секрет за постоянное время.

    Пустой ``secret`` никогда не совпадает — даже если ``provided`` тоже
    пуст: иначе в local/test с незаданным секретом любой запрос без
    заголовка проходил бы аутентификацию.
    """
    if not secret:
        return False
    return hmac.compare_digest(provided.encode(), secret.encode())


async def require_users_caller(
    x_service_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Проверить служебный секрет вызывающего (зависимость роутера).

    Принимаются оба значения — текущее и ``_PREVIOUS`` — на время
    ротации секрета, тем же приёмом, что у
    ``require_gamification_caller`` в users.
    """
    settings = get_settings()
    provided = x_service_secret or ""
    candidates = (
        settings.internal_users_secret,
        settings.internal_users_secret_previous,
    )
    if any(
        candidate is not None
        and _service_secret_matches(provided, candidate.get_secret_value())
        for candidate in candidates
    ):
        return
    raise ServiceAuthFailedError


router = APIRouter(dependencies=[Depends(require_users_caller)])


@router.post("/memberships/resolve", response_model=MembershipResolveResponse)
async def resolve_membership(
    payload: MembershipResolveRequest,
    use_case: Annotated[ResolveMembership, Depends(get_resolve_membership)],
) -> MembershipResolveResponse:
    """Разрешить членство пользователя в учреждении по запросу users.

    Нет членства, оно приостановлено или учреждения не существует — во
    всех трёх случаях один ``MembershipNotActiveError`` (404
    ``MEMBERSHIP_NOT_ACTIVE``): различать нельзя, иначе по разнице
    ответов перебором восстанавливается состав учреждений.
    """
    result: MembershipResolution = await use_case.execute(
        user_id=payload.user_id, institution_id=payload.institution_id
    )
    return MembershipResolveResponse(role=result.role.value)


@router.patch("/memberships/profile-name", response_model=ProfileNameSyncResponse)
async def sync_profile_name(
    payload: ProfileNameSyncRequest,
    use_case: Annotated[SyncProfileName, Depends(get_sync_profile_name)],
) -> ProfileNameSyncResponse:
    """Обновить ``profile_name`` во всех членствах пользователя сразу.

    Вызывается users при изменении имени в профиле (план 11, этап 3).
    Межарендная операция (``uow.for_institution(...)`` не используется) —
    см. ``SyncProfileName`` и миграцию ``0008`` про RLS-политику, которая
    это разрешает.
    """
    result: ProfileNameSyncResult = await use_case.execute(
        user_id=payload.user_id, full_name=payload.full_name
    )
    return ProfileNameSyncResponse(updated=result.updated)
