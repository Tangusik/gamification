"""Внутреннее API gamification — вызовы от других микросервисов.

Первый и пока единственный эндпоинт — ``POST /memberships/resolve``
(план `.claude/plans/10-refresh.md`, Ч2): им пользуется users при
refresh, чтобы восстановить контекст учреждения, переданный клиентом
в теле запроса, без выдачи прав, которых у пользователя уже нет.

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
from pydantic import BaseModel, ConfigDict

from app.api.deps import get_resolve_membership
from app.business.domain.internal_errors import ServiceAuthFailedError
from app.business.use_cases.context import MembershipResolution, ResolveMembership
from app.core.config import get_settings


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
