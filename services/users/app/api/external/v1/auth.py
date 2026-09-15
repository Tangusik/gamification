"""Роутер аутентификации: login, refresh, logout (план 10-refresh).

Заменяет библиотечный ``fastapi_users.get_auth_router`` целиком —
refresh-сессии не входят в контракт этого роутера, и втиснуть их в
``get_strategy``/``destroy_token`` было бы утиной подгонкой чужого
API. Пути и форма ``/login`` остаются прежними (риск 4 плана):

* ``authenticate`` + проверка ``is_active`` перед выдачей токена;
* форма отказа 400 ``LOGIN_BAD_CREDENTIALS`` (``ErrorCode`` библиотеки);
* ``on_after_login`` вызывается тем же порядком аргументов;
* ``tokenUrl`` в Swagger не меняется — путь монтирования тот же.

Refresh и logout — новые пути того же роутера (раздел 3 плана):

* путь предъявления обязан совпадать с путём выдачи (У4): ``web`` —
  только cookie, ``mobile`` — только тело запроса. Признак —
  ``X-Client: mobile``; без него путь остаётся cookie-путём (риск 9 —
  старый мобильный клиент без заголовка получит cookie и её проигнорирует,
  продолжая работать на 15-минутной сессии);
* cookie-путь требует ``X-Requested-With: gamification-web`` (У6, CSRF),
  но только когда cookie фактически предъявлена (К7, ревью Ч6): клиент
  без cookie и без claim'а обязательного заголовка не должен получать
  403 вместо единого 401/204;
* ``/login`` ставит cookie и заводит refresh-сессию веба только при том
  же заголовке ``X-Requested-With`` (К1, ревью Ч6) — иначе клиент, не
  умеющий погасить cookie при выходе (нет заголовка ни там, ни там),
  оставляет её жить на общем компьютере;
* refresh и logout принимают уже использованный токен своей цепочки
  (logout — всегда, refresh — только в окне повтора, У10/вопрос 3);
* все ответы с токенами — ``Cache-Control: no-store``.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.router.common import ErrorCode
from pydantic import BaseModel, ConfigDict

from app.api.deps import (
    get_memberships_client,
    get_refresh_session_repository,
    get_user_db,
    get_user_manager,
)
from app.auth.backend import get_jwt_strategy
from app.auth.strategy import ClaimsJWTStrategy
from app.auth.user_manager import UserManager
from app.business.domain.entities import (
    CLIENT_MOBILE,
    CLIENT_WEB,
    RefreshSession,
    hash_refresh_token,
)
from app.business.domain.errors import CsrfCheckFailedError, RefreshTokenInvalidError
from app.business.use_cases.refresh import RefreshRejectedError
from app.business.use_cases.refresh import refresh_session as run_refresh_session
from app.clients.gamification_memberships import GamificationMembershipsClient
from app.core.config import Settings, get_settings
from app.repositories.protocols import RefreshSessionRepository, UserRepository

router = APIRouter()

REFRESH_COOKIE_NAME = "gamification_refresh"
CLIENT_HEADER_NAME = "X-Client"
CSRF_HEADER_NAME = "X-Requested-With"
CSRF_HEADER_VALUE = "gamification-web"


class RefreshRequest(BaseModel):
    """Тело ``POST /refresh``.

    ``extra="forbid"``: лишнее поле в теле — признак рассинхронизации
    контракта клиента, а не то, что можно молча проигнорировать.
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None
    institution_id: uuid.UUID | None = None


class LogoutRequest(BaseModel):
    """Тело ``POST /logout`` мобильного клиента."""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str | None = None


def _resolve_client(request: Request) -> str:
    """Определить тип клиента по заголовку ``X-Client`` (вопрос 6 = А).

    Отсутствие заголовка — это ``web``, а не ошибка: старые мобильные
    клиенты (риск 9) и веб оба молчат про ``X-Client`` сегодня.
    """
    value = (request.headers.get(CLIENT_HEADER_NAME) or "").strip().lower()
    return CLIENT_MOBILE if value == CLIENT_MOBILE else CLIENT_WEB


def _has_csrf_header(request: Request) -> bool:
    """Заголовок CSRF присутствует и равен ожидаемому значению (У6)."""
    return request.headers.get(CSRF_HEADER_NAME) == CSRF_HEADER_VALUE


def _require_csrf_header(request: Request) -> None:
    """Потребовать заголовок CSRF на cookie-пути (У6)."""
    if not _has_csrf_header(request):
        raise CsrfCheckFailedError


def _is_web_client_request(request: Request) -> bool:
    """Веб-клиент, явно назвавшийся (К1): заголовок CSRF на входе.

    Отличается от ``_resolve_client``: там отсутствие ``X-Client``
    трактуется как ``web`` (путь предъявления refresh не меняется —
    У4). Здесь же нужен более узкий признак для решения о выдаче
    cookie на ``/login``, иначе старая вкладка веба или старый APK
    без единого заголовка получили бы cookie, которую никогда не
    погасят при выходе (К1).
    """
    return _has_csrf_header(request)


def _ttls_for_client(settings: Settings, client: str) -> tuple[timedelta, timedelta]:
    """Вернуть ``(idle_ttl, absolute_ttl)`` для типа клиента (вопрос 4 = Б)."""
    if client == CLIENT_MOBILE:
        return (
            timedelta(days=settings.refresh_mobile_idle_days),
            timedelta(days=settings.refresh_mobile_absolute_days),
        )
    return (
        timedelta(days=settings.refresh_web_idle_days),
        timedelta(days=settings.refresh_web_absolute_days),
    )


def _cookie_path(settings: Settings) -> str:
    """Путь cookie: узкий, совпадает с путём монтирования этого роутера.

    Снаружи (через шлюз) это ``/api/v1/users/auth/jwt`` (У5) —
    ``root_path`` добавляет именно этот внешний префикс.
    """
    return f"{settings.root_path}/users/auth/jwt"


def _cookie_max_age(session: RefreshSession) -> int:
    """``Max-Age`` — остаток абсолютного срока жизни сессии (У5)."""
    remaining = (session.absolute_expires_at - datetime.now(UTC)).total_seconds()
    return max(int(remaining), 0)


def _set_refresh_cookie(
    response: Response,
    raw_refresh_token: str,
    session: RefreshSession,
    settings: Settings,
) -> None:
    """Выставить refresh-cookie по контракту У5.

    Префикс ``__Host-`` не используется: он требует ``Path=/``, а
    здесь узкий путь — осознанное несовместимое сочетание (У5).
    """
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        raw_refresh_token,
        max_age=_cookie_max_age(session),
        path=_cookie_path(settings),
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    """Стереть refresh-cookie при выходе."""
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path=_cookie_path(settings),
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _bearer_token_from_header(value: str | None) -> str | None:
    """Достать токен из заголовка ``Authorization: Bearer ...``, если он есть."""
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return token


@router.post("/login")
async def login(
    request: Request,
    credentials: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    strategy: Annotated[ClaimsJWTStrategy, Depends(get_jwt_strategy)],
    session_repository: Annotated[
        RefreshSessionRepository, Depends(get_refresh_session_repository)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    """Вход: форма как у библиотечного роутера, плюс выдача refresh-сессии.

    Веб получает refresh только через ``Set-Cookie``, мобильный — только
    в теле ответа (У4). Заводя новую сессию, попутно чистятся просроченные
    строки прежних сессий этого пользователя (У11 — планировщика нет).

    Третья ветка (К1, ревью Ч6): клиент не назвался ни мобильным
    (``X-Client: mobile``), ни веб-клиентом, знающим про CSRF-заголовок
    (``X-Requested-With``), — старая вкладка веба до деплоя этого
    контракта или старый APK 1.0.0+1 (риск 9). Такому клиенту cookie не
    ставится и refresh-сессия не заводится вовсе: он не сможет её
    погасить при выходе (у него нет заголовка и для logout), а
    непогашенная cookie на общем компьютере — ровно риск К1. Клиент
    получает только access и продолжает работать как раньше — без
    refresh, на 15-минутной сессии.
    """
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorCode.LOGIN_BAD_CREDENTIALS,
        )

    await session_repository.delete_expired_for_user(user.id)

    access_token = await strategy.write_token(user)
    body: dict[str, str] = {"access_token": access_token, "token_type": "bearer"}

    client = _resolve_client(request)
    is_recognized_web = client == CLIENT_WEB and _is_web_client_request(request)
    session = None
    raw_refresh_token = None
    if client == CLIENT_MOBILE or is_recognized_web:
        idle_ttl, absolute_ttl = _ttls_for_client(settings, client)
        session, raw_refresh_token = await session_repository.create(
            user_id=user.id,
            client=client,
            institution_id=None,
            idle_ttl=idle_ttl,
            absolute_ttl=absolute_ttl,
        )
        if client == CLIENT_MOBILE:
            body["refresh_token"] = raw_refresh_token

    response = JSONResponse(body, headers={"Cache-Control": "no-store"})
    if is_recognized_web and session is not None and raw_refresh_token is not None:
        _set_refresh_cookie(response, raw_refresh_token, session, settings)

    await user_manager.on_after_login(user, request, response)
    return response


@router.post("/refresh")
async def refresh(
    request: Request,
    user_db: Annotated[UserRepository, Depends(get_user_db)],
    session_repository: Annotated[
        RefreshSessionRepository, Depends(get_refresh_session_repository)
    ],
    memberships: Annotated[
        GamificationMembershipsClient, Depends(get_memberships_client)
    ],
    strategy: Annotated[ClaimsJWTStrategy, Depends(get_jwt_strategy)],
    settings: Annotated[Settings, Depends(get_settings)],
    payload: Annotated[RefreshRequest | None, Body()] = None,
) -> JSONResponse:
    """Обновить пару токенов (раздел 3 плана 10-refresh).

    Один код отказа на все причины (``REFRESH_TOKEN_INVALID``) — раздел
    3: детализация — дело лога, не ответа.
    """
    body = payload or RefreshRequest()
    client = _resolve_client(request)

    if client == CLIENT_WEB:
        raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
        # CSRF требуется только при наличии cookie (К7, ревью Ч6):
        # старый APK без ``X-Client`` не носит cookie и не может
        # выставить свой заголовок, а без токена он и так получит
        # единый 401 ниже — терять код на «нет CSRF» ему незачем.
        if raw_token:
            _require_csrf_header(request)
    else:
        raw_token = body.refresh_token

    if not raw_token:
        raise RefreshTokenInvalidError

    token_hash = hash_refresh_token(raw_token)
    session = await session_repository.find(token_hash)
    if session is None or session.client != client or session.is_revoked:
        raise RefreshTokenInvalidError

    now = datetime.now(UTC)
    if session.is_expired(now=now):
        raise RefreshTokenInvalidError

    user = await user_db.get(session.user_id)
    if user is None or not user.is_active:
        raise RefreshTokenInvalidError

    # Закрыть транзакцию чтения до сетевого вызова в gamification (У3,
    # L2 ревью Ч3): иначе соединение висит «idle in transaction» на всё
    # время HTTP-запроса. Состояние сессии перечитывается заново и под
    # блокировкой внутри ``rotate`` (L1), поэтому закрывать транзакцию
    # здесь безопасно.
    await session_repository.release()

    idle_ttl, _absolute_ttl = _ttls_for_client(settings, client)
    try:
        outcome = await run_refresh_session(
            session_repository,
            memberships,
            session=session,
            token_hash=token_hash,
            requested_institution_id=body.institution_id,
            idle_ttl=idle_ttl,
            reuse_grace=timedelta(seconds=settings.refresh_reuse_grace_seconds),
        )
    except RefreshRejectedError:
        raise RefreshTokenInvalidError from None

    access_token = await strategy.write_token(user, outcome.context)

    response_body: dict[str, str] = {
        "access_token": access_token,
        "token_type": "bearer",
    }
    if client == CLIENT_MOBILE:
        response_body["refresh_token"] = outcome.raw_refresh_token

    response = JSONResponse(response_body, headers={"Cache-Control": "no-store"})
    if client == CLIENT_WEB:
        _set_refresh_cookie(
            response, outcome.raw_refresh_token, outcome.session, settings
        )
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    strategy: Annotated[ClaimsJWTStrategy, Depends(get_jwt_strategy)],
    session_repository: Annotated[
        RefreshSessionRepository, Depends(get_refresh_session_repository)
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    payload: Annotated[LogoutRequest | None, Body()] = None,
) -> Response:
    """Выход: всегда 204 (У10).

    Гасит сессию по любому токену её цепочки, в том числе уже
    использованному — logout не обязан знать, актуален ли предъявленный
    токен. Валидный access из ``Authorization``, если он есть, всё равно
    уходит в denylist, но сам по себе для выхода больше не обязателен.
    """
    body = payload or LogoutRequest()
    client = _resolve_client(request)

    if client == CLIENT_WEB:
        raw_token = request.cookies.get(REFRESH_COOKIE_NAME)
        # CSRF требуется только при наличии cookie (К7, ревью Ч6):
        # старый APK 1.0.0+1 без ``X-Client`` не носит cookie и не
        # шлёт этот заголовок. Раньше он получал 403 и переставал
        # отзывать access вовсе (риск 9) — теперь для него logout
        # снова гасит только access, сессию гасить нечем.
        if raw_token:
            _require_csrf_header(request)
    else:
        raw_token = body.refresh_token

    if raw_token:
        await session_repository.revoke_by_token(
            hash_refresh_token(raw_token), reason="logout"
        )

    access_token = _bearer_token_from_header(request.headers.get("authorization"))
    if access_token is not None:
        user = await strategy.read_token(access_token, user_manager)
        if user is not None:
            await strategy.destroy_token(access_token, user)

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    if client == CLIENT_WEB and raw_token:
        _clear_refresh_cookie(response, settings)
    return response
