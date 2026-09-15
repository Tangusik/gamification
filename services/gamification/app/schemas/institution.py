"""Pydantic-схемы API учреждений и членств (раздел 6, Ч2г плана; В5 — валюта)."""

import unicodedata
import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole

INSTITUTION_NAME_MIN_LENGTH = 1
INSTITUTION_NAME_MAX_LENGTH = 255

# Название валюты учреждения — 1..32 символа после обрезки пробелов
# (В5). Верхняя граница — предел колонки ``VARCHAR(32)``.
CURRENCY_NAME_MIN_LENGTH = 1
CURRENCY_NAME_MAX_LENGTH = 32


# ZWJ (Zero Width Joiner) — единственный символ категории Cf, который
# разрешён: без него не собираются составные эмодзи вида "👨‍👩‍👧".
_ALLOWED_FORMAT_CHARS = {"‍"}


def _normalize_currency_name(value: str) -> str:
    """Обрезать пробелы, отклонить служебные символы, проверить длину (В5).

    Тот же приём, что у ``title`` каталога (``app/schemas/market.py``):
    длина проверяется после ``strip``, а не до, иначе отступы по краям
    либо ложно укладываются в лимит, либо строка из одних пробелов
    проходит как непустая.

    Помимо пробельной обрезки отклоняются управляющие (``Cc``) и
    форматирующие (``Cf``) символы — например, zero-width-пробел
    (``​``) или направляющие письма (``‮``): они делают
    название невидимым при отображении, хотя формально строка не
    пуста (находка L1 ревью безопасности). Исключение — ZWJ
    (``‍``), нужный для составных эмодзи.
    """
    if "\x00" in value:
        raise ValueError("currency_name must not contain NUL characters")
    stripped = value.strip()
    for char in stripped:
        if char in _ALLOWED_FORMAT_CHARS:
            continue
        if unicodedata.category(char) in ("Cc", "Cf"):
            raise ValueError(
                "currency_name must not contain control or formatting characters"
            )
    if len(stripped) < CURRENCY_NAME_MIN_LENGTH:
        raise ValueError("currency_name must not be blank")
    if len(stripped) > CURRENCY_NAME_MAX_LENGTH:
        raise ValueError(
            f"currency_name must be at most {CURRENCY_NAME_MAX_LENGTH} characters "
            "after trimming"
        )
    return stripped


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
    """Тело запроса настроек учреждения: имя и/или название валюты (Ч2г, В7/S1, В5).

    ``name`` и ``currency_name`` можно передавать вместе или по
    отдельности — непереданное поле не меняется (``model_fields_set``,
    тот же приём, что у ``stock`` в `PATCH /privileges`). ``name`` нельзя
    обнулить явным ``null``: у учреждения нет смысла «без имени».
    ``currency_name``, наоборот, ``null`` обнуляет поле — фронт в этом
    случае показывает запасное слово.
    """

    name: str | None = Field(
        default=None,
        min_length=INSTITUTION_NAME_MIN_LENGTH,
        max_length=INSTITUTION_NAME_MAX_LENGTH,
    )
    currency_name: str | None = None

    @field_validator("currency_name")
    @classmethod
    def _validate_currency_name(cls, value: str | None) -> str | None:
        # ``None`` здесь означает «не передано» или явный ``null`` — обе
        # ветки различит только use case через ``model_fields_set``.
        if value is None:
            return None
        return _normalize_currency_name(value)

    @model_validator(mode="after")
    def _forbid_explicit_null_name(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name must not be null")
        return self


class InstitutionRead(BaseModel):
    """Ответ на просмотр и изменение настроек учреждения (Ч2г, В5)."""

    id: uuid.UUID
    name: str
    kind: InstitutionKind
    created_at: datetime
    currency_name: str | None


class MembershipRead(BaseModel):
    """Элемент списка собственных членств — форма как у бывшего users.

    Отдаётся вместе с названием и типом учреждения: без них клиенту
    нечего показать в переключателе. ``currency_name`` (В5) нужен и
    ученику — валюта показывается под его собственным названием уже в
    списке учреждений.
    """

    institution_id: uuid.UUID
    name: str
    kind: InstitutionKind
    role: UserRole
    status: MembershipStatus
    currency_name: str | None


class ContextTokenResponse(BaseModel):
    """Ответ переключения учреждения — та же форма, что у входа в users."""

    access_token: str
    token_type: str = "bearer"
