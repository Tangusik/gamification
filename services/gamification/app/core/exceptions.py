"""Перевод доменных исключений в HTTP-ответы.

Единственное место сервиса, где доменная ошибка становится кодом
ответа — как в ``services/users/app/core/exceptions.py``. Форма тела
ответа одна на весь сервис::

    {"detail": "MACHINE_READABLE_CODE"}

Единственное исключение — 422 от валидации FastAPI, где тело содержит
список полей с ошибками.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.auth.errors import UnauthorizedError
from app.business.domain.access_errors import (
    AccessError,
    InvalidRoleError,
    InvitationInvalidError,
)
from app.business.domain.errors import (
    ConcurrentUpdateError,
    DomainError,
    EmailAlreadyRegisteredError,
    GroupNameTakenError,
    GroupNotFoundError,
    InsufficientBalanceError,
    InvalidPasswordError,
    MemberNotFoundError,
    MembershipAlreadyExistsError,
    OperationIdConflictError,
    OutOfStockError,
    PriceChangedError,
    PrivilegeNotFoundError,
    PurchaseAlreadyResolvedError,
    PurchaseNotFoundError,
    StudentSuspendedError,
    SubjectTokenRejectedError,
    TokenIssuerContractError,
    TokenIssuerUnavailableError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
    UsersContractError,
    UsersUnavailableError,
)

logger = logging.getLogger(__name__)

# Простые доменные ошибки функций администратора (раздел «Ч2» плана):
# один код и один статус, без дополнительной логики в обработчике —
# в отличие от ``AccessError``, это не про роль/членство, а про сущности
# (учитель, группа) и внешний вызов users.
SIMPLE_DOMAIN_ERROR_RESPONSES: dict[type[DomainError], tuple[int, str]] = {
    EmailAlreadyRegisteredError: (409, "EMAIL_ALREADY_REGISTERED"),
    InvalidPasswordError: (400, "INVALID_PASSWORD"),
    MemberNotFoundError: (404, "MEMBER_NOT_FOUND"),
    GroupNotFoundError: (404, "GROUP_NOT_FOUND"),
    GroupNameTakenError: (409, "GROUP_NAME_TAKEN"),
    UsersUnavailableError: (503, "USERS_UNAVAILABLE"),
    UsersContractError: (500, "USERS_CONTRACT_ERROR"),
    # Валюта (раздел «Ч1» плана 06): начисление и сторно.
    StudentSuspendedError: (409, "STUDENT_SUSPENDED"),
    OperationIdConflictError: (409, "OPERATION_ID_CONFLICT"),
    TransactionNotFoundError: (404, "TRANSACTION_NOT_FOUND"),
    TransactionAlreadyReversedError: (409, "TRANSACTION_ALREADY_REVERSED"),
    # Маркет (план 07, Ч1): каталог и покупки.
    PrivilegeNotFoundError: (404, "PRIVILEGE_NOT_FOUND"),
    PurchaseNotFoundError: (404, "PURCHASE_NOT_FOUND"),
    OutOfStockError: (409, "OUT_OF_STOCK"),
    PriceChangedError: (409, "PRICE_CHANGED"),
    InsufficientBalanceError: (409, "INSUFFICIENT_BALANCE"),
    PurchaseAlreadyResolvedError: (409, "PURCHASE_ALREADY_RESOLVED"),
    # Гонки на уровне БД (решение владельца от 2026-09-14): дедлок и
    # serialization failure — не повреждение данных, а проигрыш гонки за
    # блокировки, клиенту нужно просто повторить запрос.
    ConcurrentUpdateError: (409, "CONCURRENT_UPDATE"),
}

# Код ответа для ошибок доступа. Всё, что не перечислено, — 403.
ACCESS_ERROR_STATUS: dict[type[AccessError], int] = {
    InvalidRoleError: 400,
    InvitationInvalidError: 404,
}
DEFAULT_ACCESS_ERROR_STATUS = 403


def access_error_status(error_type: type[AccessError]) -> int:
    """Подобрать код ответа по типу ошибки с учётом наследования."""
    for klass in error_type.__mro__:
        if klass in ACCESS_ERROR_STATUS:
            return ACCESS_ERROR_STATUS[klass]
    return DEFAULT_ACCESS_ERROR_STATUS


def _unauthorized_response() -> JSONResponse:
    """Тело и заголовок 401 — как у users, до закрытия вопроса 12 (раздел 3)."""
    return JSONResponse(
        status_code=401,
        content={"detail": "Unauthorized"},
        headers={"WWW-Authenticate": "Bearer"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Связать доменные исключения с HTTP-ответами."""

    async def access_error_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, AccessError)
        logger.info("Access denied: code=%s reason=%s", exc.code, exc)
        return JSONResponse(
            status_code=access_error_status(type(exc)), content={"detail": exc.code}
        )

    async def unauthorized_handler(request: Request, exc: Exception) -> JSONResponse:
        return _unauthorized_response()

    async def subject_token_rejected_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # Раздел 4.2: users отклонил subject-токен — клиенту та же форма
        # 401, что и при собственной проверке токена: пора на логин.
        return _unauthorized_response()

    async def membership_already_exists_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=409, content={"detail": "MEMBERSHIP_ALREADY_EXISTS"}
        )

    async def token_issuer_unavailable_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(
            status_code=503, content={"detail": "TOKEN_ISSUER_UNAVAILABLE"}
        )

    async def token_issuer_contract_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        # 422 от users — дефект вызывающего (gamification), а не
        # временная недоступность: повтор запроса не поможет.
        logger.error("Users token issuer contract violated", exc_info=exc)
        return JSONResponse(
            status_code=500, content={"detail": "TOKEN_ISSUER_CONTRACT_ERROR"}
        )

    def simple_domain_error_handler(status_code: int, code: str):
        async def handler(request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status_code, content={"detail": code})

        return handler

    async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled domain error", exc_info=exc)
        return JSONResponse(status_code=400, content={"detail": "DOMAIN_ERROR"})

    async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, HTTPException)
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code") or "ERROR"
            logger.info("HTTP error normalized: code=%s detail=%s", code, detail)
            detail = code
        return JSONResponse(
            status_code=exc.status_code, content={"detail": detail}, headers=exc.headers
        )

    # Порядок регистрации значения не имеет: Starlette ищет обработчик по
    # цепочке наследования и выбирает самый конкретный.
    app.add_exception_handler(AccessError, access_error_handler)
    app.add_exception_handler(UnauthorizedError, unauthorized_handler)
    app.add_exception_handler(SubjectTokenRejectedError, subject_token_rejected_handler)
    app.add_exception_handler(
        MembershipAlreadyExistsError, membership_already_exists_handler
    )
    app.add_exception_handler(
        TokenIssuerUnavailableError, token_issuer_unavailable_handler
    )
    app.add_exception_handler(
        TokenIssuerContractError, token_issuer_contract_error_handler
    )
    for error_type, (status_code, code) in SIMPLE_DOMAIN_ERROR_RESPONSES.items():
        app.add_exception_handler(
            error_type, simple_domain_error_handler(status_code, code)
        )
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
