"""Эндпоинты групп (Ч2б плана): создание, список, переименование, удаление,
прикрепление и открепление преподавателей и учеников.

Роутер голый: ``prefix``/``tags`` — в ``app/api/main_router.py``. У
ученика может быть несколько групп (В5/G2, против рекомендации), поэтому
прикрепление и открепление — отдельные ``PUT``/``DELETE``, идемпотентные
(повтор тоже отвечает 204).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import (
    get_add_group_student,
    get_add_group_teacher,
    get_create_group,
    get_delete_group,
    get_list_groups,
    get_remove_group_student,
    get_remove_group_teacher,
    get_update_group,
)
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.use_cases.groups import (
    AddGroupStudent,
    AddGroupTeacher,
    CreateGroup,
    DeleteGroup,
    GroupView,
    ListGroups,
    RemoveGroupStudent,
    RemoveGroupTeacher,
    UpdateGroup,
)
from app.schemas.group import GroupCreate, GroupRead, GroupUpdate

router = APIRouter()


def _to_read(view: GroupView) -> GroupRead:
    return GroupRead(
        id=view.id,
        name=view.name,
        teacher_ids=view.teacher_ids,
        students_count=view.students_count,
    )


@router.post("/{institution_id:uuid}/groups", status_code=status.HTTP_201_CREATED)
async def create_group(
    institution_id: uuid.UUID,
    payload: GroupCreate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateGroup, Depends(get_create_group)],
) -> GroupRead:
    """Завести группу; имя уникально в учреждении без учёта регистра."""
    view = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        name=payload.name,
    )
    return _to_read(view)


@router.get("/{institution_id:uuid}/groups")
async def list_groups(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListGroups, Depends(get_list_groups)],
) -> list[GroupRead]:
    """Список групп учреждения."""
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return [_to_read(view) for view in views]


@router.patch("/{institution_id:uuid}/groups/{group_id:uuid}")
async def update_group(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    payload: GroupUpdate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[UpdateGroup, Depends(get_update_group)],
) -> GroupRead:
    """Переименовать группу."""
    view = await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        name=payload.name,
    )
    return _to_read(view)


@router.delete(
    "/{institution_id:uuid}/groups/{group_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[DeleteGroup, Depends(get_delete_group)],
) -> None:
    """Удалить группу — снимает только связи, сами члены остаются."""
    await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )


@router.put(
    "/{institution_id:uuid}/groups/{group_id:uuid}/teachers/{user_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_group_teacher(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[AddGroupTeacher, Depends(get_add_group_teacher)],
) -> None:
    """Прикрепить преподавателя к группе; повтор тоже отвечает 204."""
    await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )


@router.delete(
    "/{institution_id:uuid}/groups/{group_id:uuid}/teachers/{user_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_teacher(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[RemoveGroupTeacher, Depends(get_remove_group_teacher)],
) -> None:
    """Открепить преподавателя от группы; повтор тоже отвечает 204."""
    await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )


@router.put(
    "/{institution_id:uuid}/groups/{group_id:uuid}/students/{user_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_group_student(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[AddGroupStudent, Depends(get_add_group_student)],
) -> None:
    """Прикрепить ученика к группе; повтор тоже отвечает 204 (В5/G2:
    групп у ученика может быть несколько)."""
    await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )


@router.delete(
    "/{institution_id:uuid}/groups/{group_id:uuid}/students/{user_id:uuid}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_student(
    institution_id: uuid.UUID,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[RemoveGroupStudent, Depends(get_remove_group_student)],
) -> None:
    """Открепить ученика от группы; повтор тоже отвечает 204."""
    await use_case.execute(
        institution_id=institution_id,
        group_id=group_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
