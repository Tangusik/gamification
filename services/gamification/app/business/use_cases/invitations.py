"""Use case'ы приглашений: создание, список, отзыв, принятие (раздел 5)."""

import uuid

from app.business.domain.access_errors import (
    InvitationInvalidError,
    MembershipSuspendedError,
)
from app.business.domain.entities import Invitation, create_invitation
from app.business.domain.enums import MembershipStatus, UserRole
from app.business.domain.errors import MembershipAlreadyExistsError
from app.business.domain.policies import check_role, require_institution_context
from app.business.ports import Clock, UnitOfWork
from app.business.use_cases.institutions import MembershipView

# Роли, которым доступны операции над приглашениями (F3): админ и
# преподаватель создают и видят список, отзывает автор или админ.
INVITING_ROLES = (UserRole.INSTITUTION_ADMIN, UserRole.TEACHER)


class CreateInvitation:
    """Завести приглашение (F1: бессрочное; F2: ``max_uses`` из тела)."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        max_uses: int,
    ) -> Invitation:
        require_institution_context(
            path_institution_id=institution_id,
            token_institution_id=actor_institution_id,
        )
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            membership = await scope.memberships.get_for_user(actor_user_id)
            check_role(
                active_institution_id=actor_institution_id,
                membership=membership,
                required=INVITING_ROLES,
            )
            invitation = create_invitation(
                institution_id=institution_id,
                created_by=actor_user_id,
                max_uses=max_uses,
                now=self._clock.now(),
            )
            await scope.invitations.add(invitation)
            await uow.commit()
        return invitation


class ListInvitations:
    """Список приглашений: админ видит все, преподаватель — свои (F3)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> list[Invitation]:
        require_institution_context(
            path_institution_id=institution_id,
            token_institution_id=actor_institution_id,
        )
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            membership = await scope.memberships.get_for_user(actor_user_id)
            check_role(
                active_institution_id=actor_institution_id,
                membership=membership,
                required=INVITING_ROLES,
            )
            invitations = await scope.invitations.list_all()

        assert membership is not None  # check_role уже это гарантировал
        if membership.role is UserRole.TEACHER:
            invitations = [
                invitation
                for invitation in invitations
                if invitation.created_by == actor_user_id
            ]
        return invitations


class RevokeInvitation:
    """Отозвать приглашение; отзывает автор или админ (F3).

    Преподавателю, который не видит чужое приглашение, недоступное
    приглашение отвечает так же, как несуществующее (F3, раздел 6):
    ``INVITATION_INVALID``, а не ``INSUFFICIENT_ROLE`` — иначе ответ
    выдавал бы сам факт существования приглашения.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        invitation_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        require_institution_context(
            path_institution_id=institution_id,
            token_institution_id=actor_institution_id,
        )
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            membership = await scope.memberships.get_for_user(actor_user_id)
            check_role(
                active_institution_id=actor_institution_id,
                membership=membership,
                required=INVITING_ROLES,
            )
            assert membership is not None  # check_role уже это гарантировал

            invitation = await scope.invitations.get(invitation_id)
            if invitation is None:
                raise InvitationInvalidError
            if (
                membership.role is UserRole.TEACHER
                and invitation.created_by != actor_user_id
            ):
                raise InvitationInvalidError

            await scope.invitations.revoke(invitation_id)
            await uow.commit()


class AcceptInvitation:
    """Принять приглашение по токену — контекст учреждения не нужен (F4).

    Порядок проверок — раздел 5 плана: блокировка строки, статус
    существующего членства (F7), исчерпание лимита, вставка в SAVEPOINT
    с переводом конфликта уникальности в идемпотентный ответ.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(self, *, user_id: uuid.UUID, token: str) -> MembershipView:
        async with self._uow as uow:
            invitation = await uow.invitation_lookup.get_for_accept(token)
            if invitation is None or invitation.is_revoked():
                raise InvitationInvalidError

            scope = await uow.for_institution(invitation.institution_id)
            existing = await scope.memberships.get_for_user(user_id)
            if existing is not None:
                if existing.status is not MembershipStatus.ACTIVE:
                    raise MembershipSuspendedError
                membership = existing
                await uow.commit()
            else:
                # Может бросить InvitationInvalidError (лимит исчерпан).
                new_membership = invitation.accept(
                    user_id=user_id, now=self._clock.now()
                )
                try:
                    await scope.memberships.add(new_membership)
                except MembershipAlreadyExistsError:
                    # Параллельное принятие тем же пользователем — тот же
                    # результат, что при обычном повторе (идемпотентность
                    # по построению, раздел 5).
                    membership = await scope.memberships.get_for_user(user_id)
                    await uow.commit()
                    if membership is None:
                        raise
                else:
                    await uow.invitation_lookup.increment_uses(invitation.id)
                    await uow.commit()
                    membership = new_membership

            institution = await uow.institutions.get(invitation.institution_id)

        if institution is None:
            # Институт защищён ``ON DELETE CASCADE`` от приглашения и
            # членства — эта ветка не должна быть достижима, но падать
            # молча вместо 500 без диагностики хуже.
            raise InvitationInvalidError

        return MembershipView(
            institution_id=institution.id,
            name=institution.name,
            kind=institution.kind,
            role=membership.role,
            status=membership.status,
            currency_name=institution.currency_name,
        )
