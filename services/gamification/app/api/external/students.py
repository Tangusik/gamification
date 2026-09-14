"""Эндпоинты учеников (Ч2в плана): список с фильтром по группе, изменение.

Аккаунт ученика через админа не заводится (В6/E1): ученики появляются
только по приглашениям. Роутер голый: ``prefix``/``tags`` — в
``app/api/main_router.py``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_list_students, get_update_student
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.domain.enums import MembershipStatus
from app.business.use_cases.students import ListStudents, UpdateStudent
from app.schemas.currency import StudentRead
from app.schemas.member import MemberRead, MemberUpdate

router = APIRouter()


@router.get("/{institution_id:uuid}/students")
async def list_students(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListStudents, Depends(get_list_students)],
    group_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[StudentRead]:
    """Список учеников: админ — все учреждения, преподаватель — только
    ученики своих групп (план 06, У7). Прежний элемент плюс ``balance``.
    """
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        group_id=group_id,
    )
    return [
        StudentRead(
            user_id=view.user_id,
            display_name=view.display_name,
            status=view.status,
            created_at=view.created_at,
            group_ids=view.group_ids,
            balance=view.balance,
        )
        for view in views
    ]


@router.patch("/{institution_id:uuid}/students/{user_id:uuid}")
async def update_student(
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberUpdate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[UpdateStudent, Depends(get_update_student)],
) -> MemberRead:
    """Изменить имя и/или статус ученика.

    ``MEMBER_NOT_FOUND`` — и когда ученика нет, и когда указанный
    ``user_id`` принадлежит преподавателю или админу (раздел «Умолчания»).
    """
    status_value = (
        MembershipStatus(payload.status) if payload.status is not None else None
    )
    view = await use_case.execute(
        institution_id=institution_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        display_name=payload.display_name,
        status=status_value,
    )
    return MemberRead(
        user_id=view.user_id,
        display_name=view.display_name,
        status=view.status,
        created_at=view.created_at,
        group_ids=view.group_ids,
    )
