"""Тест полноты словаря простых доменных ошибок (раздел «Ч2» плана).

Аналог ``tests/business/test_access_errors.py``, но для ошибок функций
администратора (учитель, группа, внешний вызов users) — они не про
роль/членство, поэтому не наследуют ``AccessError``.
"""

from app.business.domain.errors import (
    ConcurrentUpdateError,
    EmailAlreadyRegisteredError,
    GroupNameTakenError,
    GroupNotFoundError,
    InsufficientBalanceError,
    InvalidPasswordError,
    MemberNotFoundError,
    OperationIdConflictError,
    OutOfStockError,
    PriceChangedError,
    PrivilegeNotFoundError,
    PurchaseAlreadyResolvedError,
    PurchaseNotFoundError,
    StudentSuspendedError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
    UsersContractError,
    UsersUnavailableError,
)
from app.core.exceptions import SIMPLE_DOMAIN_ERROR_RESPONSES

EXPECTED = {
    EmailAlreadyRegisteredError: (409, "EMAIL_ALREADY_REGISTERED"),
    InvalidPasswordError: (400, "INVALID_PASSWORD"),
    MemberNotFoundError: (404, "MEMBER_NOT_FOUND"),
    GroupNotFoundError: (404, "GROUP_NOT_FOUND"),
    GroupNameTakenError: (409, "GROUP_NAME_TAKEN"),
    UsersUnavailableError: (503, "USERS_UNAVAILABLE"),
    UsersContractError: (500, "USERS_CONTRACT_ERROR"),
    StudentSuspendedError: (409, "STUDENT_SUSPENDED"),
    OperationIdConflictError: (409, "OPERATION_ID_CONFLICT"),
    TransactionNotFoundError: (404, "TRANSACTION_NOT_FOUND"),
    TransactionAlreadyReversedError: (409, "TRANSACTION_ALREADY_REVERSED"),
    PrivilegeNotFoundError: (404, "PRIVILEGE_NOT_FOUND"),
    PurchaseNotFoundError: (404, "PURCHASE_NOT_FOUND"),
    OutOfStockError: (409, "OUT_OF_STOCK"),
    PriceChangedError: (409, "PRICE_CHANGED"),
    InsufficientBalanceError: (409, "INSUFFICIENT_BALANCE"),
    PurchaseAlreadyResolvedError: (409, "PURCHASE_ALREADY_RESOLVED"),
    ConcurrentUpdateError: (409, "CONCURRENT_UPDATE"),
}


def test_catalogue_matches_expected() -> None:
    assert SIMPLE_DOMAIN_ERROR_RESPONSES == EXPECTED


def test_codes_are_unique() -> None:
    codes = [code for _, code in EXPECTED.values()]
    assert len(codes) == len(set(codes))
