"""Use case'ы создания учреждения и чтения собственных членств."""

import logging
import uuid
from dataclasses import dataclass

from app.business.domain.entities import Institution, create_institution
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.ports import Clock, UnitOfWork

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MembershipView:
    """Элемент списка собственных членств — форма ``MembershipRead`` (раздел 6)."""

    institution_id: uuid.UUID
    name: str
    kind: InstitutionKind
    role: UserRole
    status: MembershipStatus
    currency_name: str | None


class CreateInstitution:
    """Завести учреждение; создатель становится ``institution_admin`` (E1).

    Учреждение и членство создателя пишутся в одной транзакции: сбой
    после вставки учреждения не должен оставлять учреждение без
    администратора.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self, *, name: str, kind: InstitutionKind, created_by: uuid.UUID
    ) -> Institution:
        new_institution = create_institution(
            name=name, kind=kind, created_by=created_by, now=self._clock.now()
        )
        async with self._uow as uow:
            await uow.institutions.add(new_institution.institution)
            scope = await uow.for_institution(new_institution.institution.id)
            await scope.memberships.add(new_institution.admin_membership)
            await uow.commit()
        return new_institution.institution


class ListMyInstitutions:
    """Свои членства — из чего клиенту выбирать (как ``GET /users/me/institutions``)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(self, *, user_id: uuid.UUID) -> list[MembershipView]:
        async with self._uow as uow:
            memberships = await uow.user_memberships.list_for_user(user_id)
            views: list[MembershipView] = []
            for membership in memberships:
                institution = await uow.institutions.get(membership.institution_id)
                if institution is None:
                    # Членство без учреждения — дефект данных, а не
                    # действие клиента: показывать в переключателе
                    # нечего, но запись остаётся видимой в логах.
                    logger.warning(
                        "Membership %s references a missing institution",
                        membership.id,
                    )
                    continue
                views.append(
                    MembershipView(
                        institution_id=institution.id,
                        name=institution.name,
                        kind=institution.kind,
                        role=membership.role,
                        status=membership.status,
                        currency_name=institution.currency_name,
                    )
                )
            return views
