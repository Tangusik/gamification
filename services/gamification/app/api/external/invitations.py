"""Эндпоинты приглашений (раздел 5, 6 плана).

Роутер голый: ``prefix`` и ``tags`` задаются в
``app/api/main_router.py``, вместе с роутером учреждений — оба лежат
под ``/institutions``. Обработчики только разбирают запрос, зовут use
case и собирают ответ — правила живут в ``app.business``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    get_accept_invitation,
    get_create_invitation,
    get_list_invitations,
    get_revoke_invitation,
)
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.domain.entities import Invitation
from app.business.use_cases.invitations import (
    AcceptInvitation,
    CreateInvitation,
    ListInvitations,
    RevokeInvitation,
)
from app.schemas.institution import MembershipRead
from app.schemas.invitation import InvitationAccept, InvitationCreate, InvitationRead

router = APIRouter()


def _to_read(invitation: Invitation) -> InvitationRead:
    return InvitationRead(
        id=invitation.id,
        token=invitation.token,
        role=invitation.role,
        max_uses=invitation.max_uses,
        uses_count=invitation.uses_count,
        created_by=invitation.created_by,
        created_at=invitation.created_at,
        revoked_at=invitation.revoked_at,
    )


@router.post("/invitations/accept")
async def accept_invitation(
    payload: InvitationAccept,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[AcceptInvitation, Depends(get_accept_invitation)],
    response: Response,
) -> MembershipRead:
    """Принять приглашение по токену — контекст учреждения не нужен (F4).

    Путь статический (``/institutions/invitations/accept``) и не
    конфликтует с ``/institutions/{institution_id:uuid}/...``: сегмент
    ``invitations`` не проходит конвертер ``:uuid``.
    """
    view = await use_case.execute(user_id=actor.user_id, token=payload.token)
    response.headers["Cache-Control"] = "no-store"
    return MembershipRead(
        institution_id=view.institution_id,
        name=view.name,
        kind=view.kind,
        role=view.role,
        status=view.status,
        currency_name=view.currency_name,
    )


@router.post(
    "/{institution_id:uuid}/invitations",
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    institution_id: uuid.UUID,
    payload: InvitationCreate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateInvitation, Depends(get_create_invitation)],
    response: Response,
) -> InvitationRead:
    """Завести приглашение (F3: институт-админ и преподаватель)."""
    invitation = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        max_uses=payload.max_uses,
    )
    # Токен уходит в теле один раз здесь и в GET ниже — нигде дальше не
    # логируется и не должен оседать в кешах (раздел 5, риск 5).
    response.headers["Cache-Control"] = "no-store"
    return _to_read(invitation)


@router.get("/{institution_id:uuid}/invitations")
async def list_invitations(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListInvitations, Depends(get_list_invitations)],
    response: Response,
) -> list[InvitationRead]:
    """Список приглашений: админ видит все, преподаватель — свои (F3)."""
    invitations = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return [_to_read(invitation) for invitation in invitations]


@router.delete(
    "/{institution_id:uuid}/invitations/{invitation_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def revoke_invitation(
    institution_id: uuid.UUID,
    invitation_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[RevokeInvitation, Depends(get_revoke_invitation)],
) -> None:
    """Отозвать приглашение; повторный отзыв идемпотентен (F3)."""
    await use_case.execute(
        institution_id=institution_id,
        invitation_id=invitation_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
