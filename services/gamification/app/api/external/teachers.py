"""Эндпоинты преподавателей (Ч2а плана): создание, список, изменение.

Роутер голый: ``prefix`` и ``tags`` задаются в ``app/api/main_router.py``.
Доступны только ``institution_admin`` (умолчания плана).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import get_create_teacher, get_list_teachers, get_update_teacher
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.domain.enums import MembershipStatus
from app.business.use_cases.teachers import CreateTeacher, ListTeachers, UpdateTeacher
from app.schemas.member import MemberRead, MemberUpdate, TeacherCreate

router = APIRouter()


@router.post("/{institution_id:uuid}/teachers", status_code=status.HTTP_201_CREATED)
async def create_teacher(
    institution_id: uuid.UUID,
    payload: TeacherCreate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateTeacher, Depends(get_create_teacher)],
) -> MemberRead:
    """Завести преподавателя: аккаунт в users + членство ``teacher`` (В1/А1)."""
    view = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        email=payload.email,
        password=payload.password,
        display_name=payload.display_name,
    )
    return MemberRead(
        user_id=view.user_id,
        display_name=view.display_name,
        status=view.status,
        created_at=view.created_at,
        group_ids=view.group_ids,
    )


@router.get("/{institution_id:uuid}/teachers")
async def list_teachers(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListTeachers, Depends(get_list_teachers)],
) -> list[MemberRead]:
    """Список преподавателей учреждения."""
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return [
        MemberRead(
            user_id=view.user_id,
            display_name=view.display_name,
            status=view.status,
            created_at=view.created_at,
            group_ids=view.group_ids,
        )
        for view in views
    ]


@router.patch("/{institution_id:uuid}/teachers/{user_id:uuid}")
async def update_teacher(
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: MemberUpdate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[UpdateTeacher, Depends(get_update_teacher)],
) -> MemberRead:
    """Изменить имя и/или статус преподавателя.

    ``MEMBER_NOT_FOUND`` — и когда преподавателя нет, и когда указанный
    ``user_id`` принадлежит ученику или админу (раздел «Умолчания»).
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
