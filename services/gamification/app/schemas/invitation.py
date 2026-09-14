"""Pydantic-схемы API приглашений (раздел 5, 6 плана)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.business.domain.enums import UserRole

# Диапазон количества применений приглашения (F2): по умолчанию — личная
# ссылка, верхняя граница защищает от неограниченно живучей групповой.
MIN_MAX_USES = 1
MAX_MAX_USES = 100


class InvitationCreate(BaseModel):
    """Тело запроса создания приглашения."""

    max_uses: int = Field(default=1, ge=MIN_MAX_USES, le=MAX_MAX_USES)


class InvitationRead(BaseModel):
    """Элемент ответа на создание и список приглашений.

    Содержит ``token`` открытым текстом (F5, решение владельца против
    рекомендации): без него перепечатать QR нечем.
    """

    id: uuid.UUID
    token: str
    role: UserRole
    max_uses: int
    uses_count: int
    created_by: uuid.UUID
    created_at: datetime
    revoked_at: datetime | None


class InvitationAccept(BaseModel):
    """Тело запроса принятия приглашения (F4: контекст токена не нужен)."""

    token: str
