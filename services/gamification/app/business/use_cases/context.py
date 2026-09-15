"""Use case'ы переключения учреждения и разрешения членства (раздел 4)."""

import uuid
from dataclasses import dataclass

from app.business.domain.access_errors import NotAMemberError
from app.business.domain.enums import MembershipStatus, UserRole
from app.business.domain.internal_errors import MembershipNotActiveError
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


@dataclass(frozen=True)
class MembershipResolution:
    """Ответ разрешения членства для внутреннего вызова users."""

    role: UserRole


class ResolveMembership:
    """Разрешить членство пользователя в учреждении по запросу users.

    Обслуживает ``POST /internal/memberships/resolve``
    (план `.claude/plans/10-refresh.md`, Ч2): при refresh users
    восстанавливает контекст учреждения, переданный клиентом, и
    спрашивает здесь, действует ли оно ещё.

    Читает через межарендный порт ``UserMemberships.list_for_user``
    (X1) вместо ``for_institution(...).memberships.get_for_user(...)``:
    внутренний вызов не знает заранее, существует ли учреждение, а X1
    сам выставляет свой контекст (``app.user_id``) при каждом чтении и
    не полагается на предварительно открытую RLS-область — тем самым
    исключается риск молча получить 0 строк вместо ошибки на
    несуществующем или ещё не подтверждённом учреждении (риск 5 плана).

    Нет членства, оно неактивно или учреждения не существует — во всех
    трёх случаях один и тот же ``MembershipNotActiveError``: как и у
    ``SwitchInstitution``, различать нельзя, иначе по разнице ответов
    перебором восстанавливается список учреждений и состав участников.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID
    ) -> MembershipResolution:
        async with self._uow as uow:
            memberships = await uow.user_memberships.list_for_user(user_id)

        for membership in memberships:
            if (
                membership.institution_id == institution_id
                and membership.status is MembershipStatus.ACTIVE
            ):
                return MembershipResolution(role=membership.role)
        raise MembershipNotActiveError
