"""Use case переключения учреждения (раздел 4, вариант Р5-б)."""

import uuid
from dataclasses import dataclass

from app.business.domain.access_errors import NotAMemberError
from app.business.domain.enums import MembershipStatus
from app.business.ports import TokenIssuer, UnitOfWork


@dataclass(frozen=True)
class TokenPair:
    """Ответ переключения — та же форма, что у входа в users."""

    access_token: str
    token_type: str = "bearer"


class SwitchInstitution:
    """Выпустить токен в контексте выбранного учреждения.

    Нет членства, оно неактивно или учреждения не существует — во всех
    трёх случаях один и тот же ``NotAMemberError``, **без обращения в
    users** (раздел 4.1): различать нельзя, иначе по разнице ответов
    перебором восстанавливается список учреждений и состав участников.
    """

    def __init__(self, uow: UnitOfWork, token_issuer: TokenIssuer) -> None:
        self._uow = uow
        self._token_issuer = token_issuer

    async def execute(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID, subject_token: str
    ) -> TokenPair:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            membership = await scope.memberships.get_for_user(user_id)

        if membership is None or membership.status is not MembershipStatus.ACTIVE:
            raise NotAMemberError

        access_token = await self._token_issuer.issue_context_token(
            subject_token=subject_token,
            institution_id=institution_id,
            role=membership.role.value,
        )
        return TokenPair(access_token=access_token)
