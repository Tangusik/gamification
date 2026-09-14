"""Перечисления бизнес-слоя сервиса gamification.

Значения дословно повторяют ``services/users/app/domain/enums.py``:
gamification становится источником истины для учреждений и членств
(Р1), но словарь значений — общий контракт, менять его в одностороннем
порядке нельзя.
"""

from enum import StrEnum


class UserRole(StrEnum):
    """Прикладная роль пользователя в учреждении.

    ``StrEnum`` — значение уходит в JSON-ответы без конвертации,
    ``str(UserRole.STUDENT)`` даёт ``"student"``.
    """

    STUDENT = "student"
    TEACHER = "teacher"
    INSTITUTION_ADMIN = "institution_admin"


class InstitutionKind(StrEnum):
    """Тип учреждения — данные, а не ветвление в коде."""

    SCHOOL = "school"
    CAMP = "camp"


class MembershipStatus(StrEnum):
    """Состояние членства пользователя в учреждении.

    Доступ даёт только ``ACTIVE``. ``INVITED`` объявлен заранее под
    приглашения (этап 4) и на этом этапе никем не выставляется.
    """

    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"


class TransactionKind(StrEnum):
    """Тип операции с валютой (У8: хранится строкой, без ``native_enum``).

    ``PURCHASE``/``PURCHASE_REFUND`` добавлены этапом маркета (план 07,
    Ч1): покупка списывает валюту сразу (В2/M2), отказ администратора
    возвращает её отдельной записью, а не правкой покупки.
    """

    MANUAL_ACCRUAL = "manual_accrual"
    REVERSAL = "reversal"
    PURCHASE = "purchase"
    PURCHASE_REFUND = "purchase_refund"


class PurchaseStatus(StrEnum):
    """Статус покупки в маркете (план 07, В2/M2).

    ``PENDING`` — валюта уже списана, решение за администратором;
    ``FULFILLED``/``REJECTED`` — конечные состояния, назад не переходят.
    """

    PENDING = "pending"
    FULFILLED = "fulfilled"
    REJECTED = "rejected"
