"""Use case: обновление пары токенов по refresh (план 10-refresh, раздел 3).

Слой не знает про HTTP, cookie и JWT: проверки предъявленного токена,
принадлежащие HTTP-границе (CSRF, путь предъявления), и сама выдача
access-токена (``ClaimsJWTStrategy``, каркас fastapi-users) остаются в
роутере. Здесь — то, что можно проверить и решить без каркасов:

* к какому учреждению отнести новый токен (вопросы 1 и 2);
* атомарная ротация с обнаружением повтора (У2, вопрос 3) — делегирована
  порту ``RefreshSessionRepository``, только он способен гарантировать
  её одинаково для PostgreSQL и in-memory.

Порядок вызовов внутри ``refresh_session`` фиксирован владельцем (У3):
сначала вопрос членства (сетевой вызов к gamification, вне транзакции),
затем атомарная ротация. Переставлять шаги нельзя — иначе rollback
ротации после сетевой ошибки держал бы транзакцию открытой на время
HTTP-вызова.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

from app.business.domain.entities import InstitutionContext, RefreshSession
from app.business.domain.errors import (
    MembershipCheckUnavailableError,
    MembershipNotActiveError,
)
from app.business.ports import (
    RefreshSessionRepository,
    RotationOutcome,
)

logger = logging.getLogger(__name__)


class MembershipsPort(Protocol):
    """Порт проверки членства в gamification (вопрос 1 = А, раздел 3)."""

    async def resolve_role(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID
    ) -> str:
        """Вернуть роль пользователя в учреждении.

        :raises MembershipNotActiveError: 404 — членства нет, оно
            приостановлено, или учреждения не существует.
        :raises MembershipCheckUnavailableError: сеть, таймаут, 5xx,
            401 или 422 от gamification.
        """
        ...


class RefreshRejectedError(Exception):
    """Refresh отклонён — единый код ``REFRESH_TOKEN_INVALID`` наружу.

    Причина остаётся в сообщении исключения только для лога роутера —
    наружу код всегда один и тот же (раздел 3, «оракул для перебора»).
    """


@dataclass(frozen=True)
class RefreshOutcome:
    """Результат успешного refresh: новый токен цепочки и контекст."""

    session: RefreshSession
    # ``repr=False`` (I1, ревью Ч3): сырой токен не должен попадать в
    # логи и трейсбеки через дефолтный ``repr`` датакласса.
    raw_refresh_token: str = field(repr=False)
    context: InstitutionContext | None


async def resolve_institution_context(
    memberships: MembershipsPort,
    *,
    user_id: uuid.UUID,
    requested_institution_id: uuid.UUID | None,
    remembered_institution_id: uuid.UUID | None,
) -> tuple[InstitutionContext | None, uuid.UUID | None]:
    """Определить контекст нового токена и значение для сессии.

    Пустой ``requested_institution_id`` означает «взять запомненное»
    (У1, вариант А). Если и то, и другое пусто — контекста нет, и
    gamification не спрашивается вовсе.

    Возвращает пару ``(context, institution_id_for_session)`` — они
    расходятся ровно на одной ветке: gamification недоступна
    (``MembershipCheckUnavailableError``). Тогда контекст пуст, но
    запомненное значение сессии не трогается (вопрос 2 = А). При 404
    (``MembershipNotActiveError``) оба значения обнуляются — контекст
    отсутствует, и сессия забывает учреждение (раздел 3).
    """
    effective_institution_id = requested_institution_id or remembered_institution_id
    if effective_institution_id is None:
        return None, None

    try:
        role = await memberships.resolve_role(
            user_id=user_id, institution_id=effective_institution_id
        )
    except MembershipNotActiveError:
        return None, None
    except MembershipCheckUnavailableError:
        return None, remembered_institution_id

    context = InstitutionContext(institution_id=effective_institution_id, role=role)
    return context, effective_institution_id


async def refresh_session(
    repository: RefreshSessionRepository,
    memberships: MembershipsPort,
    *,
    session: RefreshSession,
    token_hash: str,
    requested_institution_id: uuid.UUID | None,
    idle_ttl: timedelta,
    reuse_grace: timedelta,
) -> RefreshOutcome:
    """Провести refresh для уже найденной и проверенной сессии.

    Проверки, которым нужен доступ к каркасам (существование и
    ``is_active`` пользователя, совпадение ``client``, срок и отзыв
    сессии — У3, шаг 2) выполняет роутер до вызова этой функции: она
    получает уже валидную ``session`` и отвечает только за вопрос
    членства и саму ротацию.

    :raises RefreshRejectedError: обнаружен повтор, либо сессия пропала
        между чтением и ротацией (гонка с параллельным logout/reuse).
    """
    context, new_institution_id = await resolve_institution_context(
        memberships,
        user_id=session.user_id,
        requested_institution_id=requested_institution_id,
        remembered_institution_id=session.institution_id,
    )

    result = await repository.rotate(
        token_hash=token_hash,
        idle_ttl=idle_ttl,
        reuse_grace=reuse_grace,
        institution_id=new_institution_id,
    )

    if result.outcome is RotationOutcome.REUSED:
        logger.warning(
            "Refresh token reuse detected: session_id=%s user_id=%s",
            result.session.id if result.session is not None else session.id,
            session.user_id,
        )
        raise RefreshRejectedError("Refresh token reuse detected")

    if result.outcome is RotationOutcome.NOT_FOUND or result.session is None:
        raise RefreshRejectedError("Session is no longer valid")

    assert result.raw_token is not None  # ROTATED всегда несёт новый токен
    return RefreshOutcome(
        session=result.session,
        raw_refresh_token=result.raw_token,
        context=context,
    )
