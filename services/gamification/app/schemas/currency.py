"""Pydantic-схемы API валюты (Ч1 плана 06)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.business.domain.enums import MembershipStatus, TransactionKind, UserRole

# Сумма — целое число 1..10 000 за операцию (У3): проверка схемы от
# опечатки, а не правило начисления.
MIN_ACCRUAL_AMOUNT = 1
MAX_ACCRUAL_AMOUNT = 10_000

# Комментарий необязателен, до 200 символов после обрезки пробелов
# (В2/C2, «Уточнения к семантике» плана).
COMMENT_MAX_LENGTH = 200


class CurrencyAccrualCreate(BaseModel):
    """Тело запроса ручного начисления (`POST
    /students/{user_id}/currency-transactions`).

    ``operation_id`` — идемпотентность по построению (В4/I1): клиент
    создаёт его при открытии формы и не меняет при повторной отправке.
    """

    operation_id: uuid.UUID
    amount: int = Field(ge=MIN_ACCRUAL_AMOUNT, le=MAX_ACCRUAL_AMOUNT)
    comment: str | None = Field(default=None)

    @field_validator("comment")
    @classmethod
    def _normalize_comment(cls, value: str | None) -> str | None:
        """Обрезать пробелы по краям; пустая строка после обрезки — ``null``.

        Длина проверяется после обрезки (не до), чтобы отступы на концах
        не давали ложный 422 на строке, которая после обрезки укладывается
        в лимит.
        """
        if value is None:
            return None
        if "\x00" in value:
            # NUL не хранится в PostgreSQL text/varchar (I1) — 422 по
            # полю, а не 500 из драйвера БД.
            raise ValueError("comment must not contain NUL characters")
        stripped = value.strip()
        if len(stripped) > COMMENT_MAX_LENGTH:
            raise ValueError(
                f"comment must be at most {COMMENT_MAX_LENGTH} characters "
                "after trimming"
            )
        return stripped or None


class CurrencyReversalCreate(BaseModel):
    """Тело запроса сторно (`POST /currency-transactions/{tx_id}/reversal`)."""

    operation_id: uuid.UUID


class CurrencyTransactionRead(BaseModel):
    """Элемент истории операций с валютой."""

    id: uuid.UUID
    kind: TransactionKind
    amount: int
    comment: str | None
    created_by_name: str | None
    created_by_role: UserRole
    created_at: datetime
    reverses_id: uuid.UUID | None


class CurrencyAccountRead(BaseModel):
    """Баланс и последние 50 операций, новые сверху (У1)."""

    balance: int
    transactions: list[CurrencyTransactionRead]


class StudentRead(BaseModel):
    """Элемент `GET /students` — форма `MemberRead` плюс `balance`.

    Отдельная схема, а не расширение ``MemberRead``: ответ `GET
    /teachers` эту схему не использует и не меняется (план 06, раздел
    «Хранилище и слой»).
    """

    user_id: uuid.UUID
    display_name: str | None
    status: MembershipStatus
    created_at: datetime
    group_ids: list[uuid.UUID]
    balance: int
