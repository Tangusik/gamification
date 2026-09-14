"""Use case'ы учеников (Ч2в плана, Ч1 плана 06): список с фильтром по
группе, изменение.

Аккаунт ученика через админа не заводится (В6/E1): ученики появляются
только по приглашениям (уже реализовано, ``use_cases/invitations.py``).
"""

import uuid
from dataclasses import dataclass

from app.business.domain.entities import Membership
from app.business.domain.enums import MembershipStatus, UserRole
from app.business.domain.errors import GroupNotFoundError, MemberNotFoundError
from app.business.ports import UnitOfWork
from app.business.use_cases.access import (
    require_admin_or_teacher,
    require_institution_admin,
)
from app.business.use_cases.members import MemberView, apply_member_update


@dataclass(frozen=True)
class StudentView(MemberView):
    """Элемент ``GET /students`` — форма ``MemberRead`` плюс ``balance``
    (план 06, раздел «Контракт»): ответ ``GET /teachers`` эту схему не
    использует и не меняется.
    """

    balance: int = 0


class ListStudents:
    """Список учеников: админ — все учреждения, преподаватель — только
    ученики своих групп (У7, план 06 В1/А2).

    :raises GroupNotFoundError: указанная группа не найдена в этом
        учреждении, а преподавателю — и на существующую чужую группу
        (один код на оба случая, план 06).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        group_id: uuid.UUID | None,
    ) -> list[StudentView]:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor = await require_admin_or_teacher(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            is_teacher = actor.role is UserRole.TEACHER
            teacher_group_ids: set[uuid.UUID] = set()
            if is_teacher:
                teacher_group_ids = set(
                    await scope.groups.list_group_ids_for_teacher(actor.id)
                )

            if group_id is not None:
                if await scope.groups.get(group_id) is None:
                    raise GroupNotFoundError
                if is_teacher and group_id not in teacher_group_ids:
                    raise GroupNotFoundError

            students = await scope.memberships.list_by_role(UserRole.STUDENT)
            balances = await scope.currency.list_balances(
                [student.id for student in students]
            )
            views = []
            for student in students:
                student_group_ids = await scope.groups.list_group_ids_for_student(
                    student.id
                )
                if is_teacher:
                    visible_group_ids = [
                        gid for gid in student_group_ids if gid in teacher_group_ids
                    ]
                    if not visible_group_ids:
                        continue
                else:
                    visible_group_ids = student_group_ids
                if group_id is not None and group_id not in visible_group_ids:
                    continue
                views.append(
                    StudentView(
                        user_id=student.user_id,
                        display_name=student.display_name,
                        status=student.status,
                        created_at=student.created_at,
                        group_ids=visible_group_ids,
                        balance=balances.get(student.id, 0),
                    )
                )
            return views


class UpdateStudent:
    """Изменить имя и/или статус ученика (Ч2в).

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
            student = await scope.memberships.get_for_user(target_user_id)
            if student is None or student.role is not UserRole.STUDENT:
                raise MemberNotFoundError
            updated = apply_member_update(
                student, display_name=display_name, status=status
            )
            await scope.memberships.update(updated)
            # До commit (риск 2 плана 07a): group_ids читает group_students
            # — RLS-таблицу, чей контекст истекает вместе с транзакцией.
            group_ids = await scope.groups.list_group_ids_for_student(updated.id)
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
