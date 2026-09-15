"""Перевод доменных исключений в HTTP-ответы.

Единственное место сервиса, где доменная ошибка превращается в код
ответа. Домен и прикладной слой про HTTP не знают — это позволяет
переиспользовать те же проверки вне HTTP, в потребителе событий или
фоновой задаче.

Форма тела ответа одна на весь сервис::

    {"detail": "MACHINE_READABLE_CODE"}

Строка, а не объект: клиент разбирает один формат, а не два. Единственное
исключение — 422 от валидации FastAPI, где тело содержит список полей с
ошибками. Схлопывать его в одну строку нельзя, иначе формы потеряют
информацию о том, какое поле неверно.
"""

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.business.domain.errors import (
    CsrfCheckFailedError,
    DomainError,
    RefreshTokenInvalidError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.business.domain.internal_errors import (
    InternalApiError,
    PasswordRejectedError,
    ServiceAuthFailedError,
)
from app.business.domain.internal_errors import (
    UserAlreadyExistsError as InternalUserAlreadyExistsError,
)

logger = logging.getLogger(__name__)

# Код ответа для ошибок внутреннего API. Отдельное пространство от
# ошибок доступа конечного пользователя (оно уехало в gamification
# вместе с членствами) — см. ``.claude/knowledge/08-api-contract.md``.
INTERNAL_ERROR_STATUS: dict[type[InternalApiError], int] = {
    ServiceAuthFailedError: 401,
    InternalUserAlreadyExistsError: 409,
    PasswordRejectedError: 400,
}
DEFAULT_INTERNAL_ERROR_STATUS = 403


def internal_error_status(error_type: type[InternalApiError]) -> int:
    """Подобрать код ответа по типу ошибки внутреннего API."""
    for klass in error_type.__mro__:
        if klass in INTERNAL_ERROR_STATUS:
            return INTERNAL_ERROR_STATUS[klass]
    return DEFAULT_INTERNAL_ERROR_STATUS


def register_exception_handlers(app: FastAPI) -> None:
    """Связать доменные исключения с HTTP-ответами."""

    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Ответить кодом из пространства внутреннего API.

        Подробности (какой именно секрет или почему токен отвергнут) в
        ответ не идут — только код и запись в лог, без самого токена и
        без секрета.
        """
        assert isinstance(exc, InternalApiError)
        logger.warning("Internal API rejected a call: code=%s", exc.code)
        return JSONResponse(
            status_code=internal_error_status(type(exc)), content={"detail": exc.code}
        )

    async def user_already_exists_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "USER_ALREADY_EXISTS"})

    async def user_not_found_handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "USER_NOT_FOUND"})

    async def refresh_token_invalid_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Единый код на все причины отказа refresh-токена (план 10-refresh).

        ``no-store``: ответ мог бы содержать (а на успехе — содержит)
        токен, кешировать такой путь нельзя нигде, включая отказ.
        """
        return JSONResponse(
            status_code=401,
            content={"detail": "REFRESH_TOKEN_INVALID"},
            headers={"Cache-Control": "no-store"},
        )

    async def csrf_check_failed_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": "CSRF_CHECK_FAILED"})

    async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled domain error", exc_info=exc)
        return JSONResponse(status_code=400, content={"detail": "DOMAIN_ERROR"})

    async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Свести тело HTTP-ошибки к строке кода.

        Нужен из-за ``fastapi-users``: часть его ответов отдаёт
        ``detail`` объектом (``{"code": ..., "reason": ...}``), а часть —
        строкой. Без нормализации клиент разбирал бы два формата, а
        каталог кодов раздваивался бы на «строковые» и «объектные».
        Причина отказа из объекта уходит в лог.
        """
        assert isinstance(exc, HTTPException)
        detail = exc.detail
        if isinstance(detail, dict):
            code = detail.get("code") or "ERROR"
            logger.info("HTTP error normalized: code=%s detail=%s", code, detail)
            detail = code
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": detail},
            headers=exc.headers,
        )

    # Порядок регистрации значения не имеет: Starlette ищет обработчик по
    # цепочке наследования и выбирает самый конкретный. Поэтому
    # InternalApiError не перехватывается обработчиком DomainError.
    app.add_exception_handler(InternalApiError, internal_error_handler)
    app.add_exception_handler(UserAlreadyExistsError, user_already_exists_handler)
    app.add_exception_handler(UserNotFoundError, user_not_found_handler)
    app.add_exception_handler(RefreshTokenInvalidError, refresh_token_invalid_handler)
    app.add_exception_handler(CsrfCheckFailedError, csrf_check_failed_handler)
    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
