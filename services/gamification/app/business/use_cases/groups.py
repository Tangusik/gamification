"""Use case'ы групп (Ч2б плана): создание, список, переименование, удаление,
прикрепление и открепление преподавателей и учеников.

У ученика может быть несколько групп (В5/G2, против рекомендации) —
поэтому прикрепление и открепление ученика идёт отдельными
``PUT``/``DELETE``, как и у преподавателя, а не полем на членстве.
"""

import uuid
from dataclasses import dataclass

from app.business.domain.entities import Group, Membership
from app.business.domain.enums import UserRole
from app.business.domain.errors import GroupNotFoundError, MemberNotFoundError
from app.business.ports import Clock, InstitutionScope, UnitOfWork
from app.business.use_cases.access import (
    require_admin_or_teacher,
    require_institution_admin,
)


@dataclass(frozen=True)
class GroupView:
    """Элемент ответа группы — форма ``GroupRead`` (Ч2б)."""

    id: uuid.UUID
    name: str
    teacher_ids: list[uuid.UUID]
    students_count: int


class CreateGroup:
    """Завести группу (Ч2б).

    :raises GroupNameTakenError: имя занято без учёта регистра.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        name: str,
    ) -> GroupView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            group = Group(
                id=uuid.uuid4(),
                institution_id=institution_id,
                name=name,
                created_at=self._clock.now(),
            )
            await scope.groups.add(group)
            await uow.commit()
        return GroupView(id=group.id, name=group.name, teacher_ids=[], students_count=0)


class ListGroups:
    """Список групп учреждения: админ — все, преподаватель — свои (У7)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> list[GroupView]:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor = await require_admin_or_teacher(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            groups = await scope.groups.list_all()
            if actor.role is UserRole.TEACHER:
                teacher_group_ids = set(
                    await scope.groups.list_group_ids_for_teacher(actor.id)
                )
                groups = [group for group in groups if group.id in teacher_group_ids]
            views = []
            for group in groups:
                views.append(await _to_view(scope, group))
            return views


class UpdateGroup:
    """Переименовать группу (Ч2б).

    :raises GroupNotFoundError: группы нет в этом учреждении.
    :raises GroupNameTakenError: новое имя занято другой группой.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        name: str,
    ) -> GroupView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            group = await scope.groups.rename(group_id, name)
            if group is None:
                raise GroupNotFoundError
            # До commit (риск 2 плана 07a): _to_view читает group_teachers
            # и group_students — RLS-таблицы, чей контекст истекает вместе
            # с транзакцией коммита.
            view = await _to_view(scope, group)
            await uow.commit()
        return view


class DeleteGroup:
    """Удалить группу — снимает только связи, сами члены остаются (Ч2б).

    :raises GroupNotFoundError: группы нет в этом учреждении.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            deleted = await scope.groups.delete(group_id)
            if not deleted:
                raise GroupNotFoundError
            await uow.commit()


class _GroupMembershipUseCase:
    """Общая проверка для прикрепления/открепления преподавателя и ученика.

    :raises GroupNotFoundError: группы нет в этом учреждении.
    :raises MemberNotFoundError: члена нет, он в другом учреждении или у
        него не та роль (например, ученик там, где ожидается
        преподаватель).
    """

    required_role: UserRole

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def _resolve(
        self, scope: InstitutionScope, *, group_id: uuid.UUID, user_id: uuid.UUID
    ) -> Membership:
        group = await scope.groups.get(group_id)
        if group is None:
            raise GroupNotFoundError
        membership = await scope.memberships.get_for_user(user_id)
        if membership is None or membership.role is not self.required_role:
            raise MemberNotFoundError
        return membership


class AddGroupTeacher(_GroupMembershipUseCase):
    """Прикрепить преподавателя к группе; идемпотентно (Ч2б)."""

    required_role = UserRole.TEACHER

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            membership = await self._resolve(
                scope, group_id=group_id, user_id=target_user_id
            )
            await scope.groups.add_teacher(
                group_id=group_id, membership_id=membership.id
            )
            await uow.commit()


class RemoveGroupTeacher(_GroupMembershipUseCase):
    """Открепить преподавателя от группы; идемпотентно (Ч2б)."""

    required_role = UserRole.TEACHER

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            membership = await self._resolve(
                scope, group_id=group_id, user_id=target_user_id
            )
            await scope.groups.remove_teacher(
                group_id=group_id, membership_id=membership.id
            )
            await uow.commit()


class AddGroupStudent(_GroupMembershipUseCase):
    """Прикрепить ученика к группе; идемпотентно (Ч2в: групп может быть
    несколько, В5/G2).
    """

    required_role = UserRole.STUDENT

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            membership = await self._resolve(
                scope, group_id=group_id, user_id=target_user_id
            )
            await scope.groups.add_student(
                group_id=group_id, membership_id=membership.id
            )
            await uow.commit()


class RemoveGroupStudent(_GroupMembershipUseCase):
    """Открепить ученика от группы; идемпотентно (Ч2в)."""

    required_role = UserRole.STUDENT

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        group_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> None:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            membership = await self._resolve(
                scope, group_id=group_id, user_id=target_user_id
            )
            await scope.groups.remove_student(
                group_id=group_id, membership_id=membership.id
            )
            await uow.commit()


async def _to_view(scope: InstitutionScope, group: Group) -> GroupView:
    teacher_ids = await scope.groups.list_teacher_user_ids(group.id)
    students_count = await scope.groups.count_students(group.id)
    return GroupView(
        id=group.id,
        name=group.name,
        teacher_ids=teacher_ids,
        students_count=students_count,
    )
