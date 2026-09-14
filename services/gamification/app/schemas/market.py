"""Pydantic-схемы API маркета (план 07, Ч1): каталог и покупки."""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.business.domain.enums import PurchaseStatus

# Цена — целое 1..100 000 (У6). Название 1..100 символов, описание —
# ≤ 500 или null.
MIN_PRICE = 1
MAX_PRICE = 100_000
TITLE_MIN_LENGTH = 1
TITLE_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 500
MIN_STOCK = 0

# Поля позиции, которые ``PATCH`` не может обнулить явным ``null`` (У11):
# у них нет доменного смысла «без значения».
NON_NULLABLE_UPDATE_FIELDS = ("title", "price", "is_active")


def _normalize_title(value: str) -> str:
    """Обрезать пробелы, отклонить NUL, проверить длину после обрезки (У6).

    Длина и пустота проверяются после ``strip`` (не до), как у
    ``comment`` этапа 06 (``app/schemas/currency.py``), — иначе отступы
    по краям либо дают ложный 422 в пределах лимита, либо пропускают
    строку из одних пробелов.
    """
    if "\x00" in value:
        # NUL не хранится в PostgreSQL text/varchar — 422 по полю, а не
        # 500 из драйвера БД (SQLSTATE 22021).
        raise ValueError("title must not contain NUL characters")
    stripped = value.strip()
    if len(stripped) < TITLE_MIN_LENGTH:
        raise ValueError("title must not be blank")
    if len(stripped) > TITLE_MAX_LENGTH:
        raise ValueError(
            f"title must be at most {TITLE_MAX_LENGTH} characters after trimming"
        )
    return stripped


def _normalize_description(value: str | None) -> str | None:
    """Обрезать пробелы; пустая строка после обрезки — ``null`` (У6)."""
    if value is None:
        return None
    if "\x00" in value:
        raise ValueError("description must not contain NUL characters")
    stripped = value.strip()
    if len(stripped) > DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            f"description must be at most {DESCRIPTION_MAX_LENGTH} characters "
            "after trimming"
        )
    return stripped or None


class PrivilegeCreate(BaseModel):
    """Тело `POST /privileges` — только admin (П2).

    ``stock`` без поля в теле — ``None`` (без ограничения, В5/L2,
    подтверждено владельцем в разделе 9 плана).
    """

    title: str
    description: str | None = None
    price: int = Field(ge=MIN_PRICE, le=MAX_PRICE)
    # Верхняя граница — предел колонки `integer` (SQLSTATE 22003), не
    # бизнес-лимит: другого лимита план не задаёт.
    stock: int | None = Field(default=None, ge=MIN_STOCK, le=2_147_483_647)
    is_active: bool = True

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        return _normalize_title(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)


class PrivilegeUpdate(BaseModel):
    """Тело `PATCH /privileges/{id}` — только admin (У11).

    Любое поле необязательно; поле, не переданное в теле, не меняется.
    ``description``/``stock`` можно явно обнулить (``null`` — «нет
    описания»/«без ограничения»), остальные поля — нет: сервер различает
    «не передано» и «null» через ``model_fields_set``, а не через
    ``None`` как признак отсутствия (тот приём не различил бы «не
    передано» и «явный null», план 07 У11).
    """

    title: str | None = None
    description: str | None = None
    price: int | None = Field(default=None, ge=MIN_PRICE, le=MAX_PRICE)
    # Верхняя граница — предел колонки `integer`, не бизнес-лимит.
    stock: int | None = Field(default=None, ge=MIN_STOCK, le=2_147_483_647)
    is_active: bool | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        # ``None`` здесь означает «не передано» или «явный null» — обе
        # ветки различит только `model_validator` ниже
        # (``model_fields_set``), нормализация трогает лишь непустое
        # значение.
        if value is None:
            return None
        return _normalize_title(value)

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)

    @model_validator(mode="after")
    def _forbid_explicit_null_on_non_nullable_fields(self) -> Self:
        for field_name in NON_NULLABLE_UPDATE_FIELDS:
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                raise ValueError(f"{field_name} must not be null")
        return self


class PrivilegeRead(BaseModel):
    """Элемент каталога (план 07, раздел «Эндпоинты»)."""

    id: uuid.UUID
    title: str
    description: str | None
    price: int
    stock: int | None
    is_active: bool


class PurchaseCreate(BaseModel):
    """Тело `POST /purchases` — только student.

    ``operation_id`` — идемпотентность (П4/И1, тот же приём, что у
    валюты); ``expected_price`` — защита от смены цены (У5).
    """

    operation_id: uuid.UUID
    privilege_id: uuid.UUID
    expected_price: int = Field(ge=MIN_PRICE, le=MAX_PRICE)


class PurchaseRead(BaseModel):
    """Покупка (раздел 9 плана — контракт подтверждён владельцем):
    ``user_id``/``user_name`` заполнены только в админском списке и
    решениях админа, у student — всегда ``None``.
    """

    id: uuid.UUID
    privilege_id: uuid.UUID
    title: str
    price: int
    status: PurchaseStatus
    created_at: datetime
    resolved_at: datetime | None
    user_id: uuid.UUID | None = None
    user_name: str | None = None
