"""Pydantic-схемы API учреждений и членств (раздел 6, Ч2г плана)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole

INSTITUTION_NAME_MIN_LENGTH = 1
INSTITUTION_NAME_MAX_LENGTH = 255


class InstitutionCreate(BaseModel):
    """Тело запроса создания учреждения."""

    name: str = Field(
        min_length=INSTITUTION_NAME_MIN_LENGTH, max_length=INSTITUTION_NAME_MAX_LENGTH
    )
    kind: InstitutionKind = InstitutionKind.SCHOOL


class InstitutionCreated(BaseModel):
    """Ответ на создание учреждения — только идентификатор."""

    id: uuid.UUID


class InstitutionUpdate(BaseModel):
    """Тело запроса переименования учреждения (Ч2г, В7/S1).

    Та же валидация имени, что при создании; ``kind`` этим этапом не
    меняется.
    """

    name: str = Field(
        min_length=INSTITUTION_NAME_MIN_LENGTH, max_length=INSTITUTION_NAME_MAX_LENGTH
    )


class InstitutionRead(BaseModel):
    """Ответ на просмотр и переименование учреждения (Ч2г)."""

    id: uuid.UUID
    name: str
    kind: InstitutionKind
    created_at: datetime


class MembershipRead(BaseModel):
    """Элемент списка собственных членств — форма как у бывшего users.

    Отдаётся вместе с названием и типом учреждения: без них клиенту
    нечего показать в переключателе.
    """

    institution_id: uuid.UUID
    name: str
    kind: InstitutionKind
    role: UserRole
    status: MembershipStatus


class ContextTokenResponse(BaseModel):
    """Ответ переключения учреждения — та же форма, что у входа в users."""

    access_token: str
    token_type: str = "bearer"
