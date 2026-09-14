"""Use case'ы преподавателей (Ч2а плана): создание, список, изменение."""

import logging
import uuid

from app.business.domain.entities import Membership
from app.business.domain.enums import MembershipStatus, UserRole
from app.business.domain.errors import MemberNotFoundError
from app.business.ports import Clock, UnitOfWork, UserAccounts
from app.business.use_cases.access import require_institution_admin
from app.business.use_cases.members import MemberView, apply_member_update


class CreateTeacher:
    """Завести преподавателя (В1/А1): аккаунт в users + членство ``teacher``.

    Порядок — раздел «Умолчания» плана: права и валидация, затем вызов
    users **без открытой транзакции БД** (как в ``SwitchInstitution``),
    затем вставка членства и коммит одной транзакцией.
    """

    def __init__(
        self, uow: UnitOfWork, clock: Clock, user_accounts: UserAccounts
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._user_accounts = user_accounts

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        email: str,
        password: str,
        display_name: str,
    ) -> MemberView:
        # Шаг 1: права и валидация — в отдельной, закрытой до вызова
        # users транзакции (соединение с БД не удерживается на время
        # HTTP-ожидания, тот же приём, что и у переключения учреждения).
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )

        # Шаг 2: вызов users без открытой транзакции БД.
        new_user_id = await self._user_accounts.create_account(
            email=email, password=password
        )

        # Шаг 3: вставка членства и коммит. Сбой здесь оставляет аккаунт
        # без членства (риск 1 плана, error-лог для ручного разбора).
        now = self._clock.now()
        membership = Membership(
            id=uuid.uuid4(),
            user_id=new_user_id,
            institution_id=institution_id,
            role=UserRole.TEACHER,
            status=MembershipStatus.ACTIVE,
            created_at=now,
            display_name=display_name,
        )
        try:
            async with self._uow as uow:
                scope = await uow.for_institution(institution_id)
                await scope.memberships.add(membership)
                await uow.commit()
        except Exception:
            logging.getLogger(__name__).error(
                "Teacher account created in users but membership insert "
                "failed: user_id=%s",
                new_user_id,
            )
            raise

        return MemberView(
            user_id=membership.user_id,
            display_name=membership.display_name,
            status=membership.status,
            created_at=membership.created_at,
            group_ids=[],
        )


class ListTeachers:
    """Список преподавателей учреждения (Ч2а)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> list[MemberView]:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            teachers = await scope.memberships.list_by_role(UserRole.TEACHER)
            views = []
            for teacher in teachers:
                group_ids = await scope.groups.list_group_ids_for_teacher(teacher.id)
                views.append(_to_view(teacher, group_ids))
            return views


class UpdateTeacher:
    """Изменить имя и/или статус преподавателя (Ч2а).

    :raises MemberNotFoundError: члена нет, он в другой роли или в другом
        учреждении (раздел «Умолчания» — один код на все три случая).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        display_name: str | None,
        status: MembershipStatus | None,
    ) -> MemberView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            teacher = await scope.memberships.get_for_user(target_user_id)
            if teacher is None or teacher.role is not UserRole.TEACHER:
                raise MemberNotFoundError
            updated = apply_member_update(
                teacher, display_name=display_name, status=status
            )
            await scope.memberships.update(updated)
            # До commit (риск 2 плана 07a): group_ids читает group_teachers
            # — RLS-таблицу, чей контекст истекает вместе с транзакцией.
            group_ids = await scope.groups.list_group_ids_for_teacher(updated.id)
            await uow.commit()
        return _to_view(updated, group_ids)


def _to_view(membership: Membership, group_ids: list[uuid.UUID]) -> MemberView:
    return MemberView(
        user_id=membership.user_id,
        display_name=membership.display_name,
        status=membership.status,
        created_at=membership.created_at,
        group_ids=group_ids,
    )
