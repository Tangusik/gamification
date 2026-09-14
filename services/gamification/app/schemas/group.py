"""Pydantic-схемы API групп (Ч2б плана)."""

import uuid

from pydantic import BaseModel, Field

GROUP_NAME_MIN_LENGTH = 1
GROUP_NAME_MAX_LENGTH = 100


class GroupCreate(BaseModel):
    """Тело запроса создания группы."""

    name: str = Field(
        min_length=GROUP_NAME_MIN_LENGTH, max_length=GROUP_NAME_MAX_LENGTH
    )


class GroupUpdate(BaseModel):
    """Тело запроса переименования группы."""

    name: str = Field(
        min_length=GROUP_NAME_MIN_LENGTH, max_length=GROUP_NAME_MAX_LENGTH
    )


class GroupRead(BaseModel):
    """Ответ на создание, список и изменение группы."""

    id: uuid.UUID
    name: str
    teacher_ids: list[uuid.UUID]
    students_count: int
