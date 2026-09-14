"""Pydantic-схемы API преподавателей и учеников (Ч2а, Ч2в плана)."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.business.domain.enums import MembershipStatus

DISPLAY_NAME_MIN_LENGTH = 1
DISPLAY_NAME_MAX_LENGTH = 100

# ``status`` принимает только эти два значения (раздел «Умолчания»):
# ``invited`` этим эндпоинтам не проставляется.
MemberStatusInput = Literal["active", "suspended"]


class TeacherCreate(BaseModel):
    """Тело запроса создания преподавателя (В1/А1: аккаунт заводит gamification)."""

    email: EmailStr
    password: str = Field(min_length=1)
    display_name: str = Field(
        min_length=DISPLAY_NAME_MIN_LENGTH, max_length=DISPLAY_NAME_MAX_LENGTH
    )


class MemberUpdate(BaseModel):
    """Тело запроса изменения преподавателя или ученика (Ч2а, Ч2в).

    Оба поля необязательны и применяются, только если пришли: обнулить
    уже заполненное имя через ``PATCH`` в этом этапе нельзя (минимальный
    вариант — см. базу знаний).
    """

    display_name: str | None = Field(
        default=None,
        min_length=DISPLAY_NAME_MIN_LENGTH,
        max_length=DISPLAY_NAME_MAX_LENGTH,
    )
    status: MemberStatusInput | None = None


class MemberRead(BaseModel):
    """Элемент списка преподавателей/учеников (Ч2а, Ч2в)."""

    user_id: uuid.UUID
    display_name: str | None
    status: MembershipStatus
    created_at: datetime
    group_ids: list[uuid.UUID]
