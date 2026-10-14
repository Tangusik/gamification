"""Use case'ы создания учреждения и чтения собственных членств."""

import logging
import uuid
from dataclasses import dataclass

from app.business.domain.entities import Institution, create_institution
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import UsersContractError, UsersUnavailableError
from app.business.ports import Clock, UnitOfWork, UserAccounts

logger = logging.getLogger(__name__)


async def get_profile_name_or_none(
    user_accounts: UserAccounts, user_id: uuid.UUID
) -> str | None:
    """Профильное имя из users, не повод отказать человеку в операции.

    Общий приём для ``CreateInstitution`` и ``AcceptInvitation`` (план
    11, этап 2, п. 6 раздела «Что сделать»): недоступность users или
    ответ не по контракту не должны блокировать создание учреждения или
    принятие приглашения — только warning в лог и ``profile_name=None``,
    имя доедет этапом 3 (синхронизацией).
    """
    try:
        return await user_accounts.get_full_name(user_id)
    except (UsersUnavailableError, UsersContractError):
        logger.warning(
            "Could not fetch profile name from users for user_id=%s; "
            "membership will be created without profile_name",
            user_id,
        )
        return None


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

    def __init__(
        self, uow: UnitOfWork, clock: Clock, user_accounts: UserAccounts
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._user_accounts = user_accounts

    async def execute(
        self, *, name: str, kind: InstitutionKind, created_by: uuid.UUID
    ) -> Institution:
        # Профильное имя создателя — вне открытой транзакции БД, тот же
        # приём, что в CreateTeacher (use_cases/teachers.py). Имя — не
        # повод отказать владельцу в создании учреждения: недоступность
        # users или ответ не по контракту дают только warning и
        # profile_name=None, имя доедет этапом 3 (синхронизацией).
        profile_name = await get_profile_name_or_none(self._user_accounts, created_by)
        new_institution = create_institution(
            name=name,
            kind=kind,
            created_by=created_by,
            now=self._clock.now(),
            profile_name=profile_name,
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
