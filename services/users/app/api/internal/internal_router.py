"""Внутреннее API сервиса users — вызовы от других микросервисов.

Эндпоинты:

* выпуск токена в контексте учреждения
  (``POST /internal/tokens/institution-context``), которым пользуется
  gamification при переключении учреждения (вариант (б),
  ``.claude/plans/03-gamification-service.md``, раздел 4);
* заведение аккаунта преподавателя с временным паролем
  (``POST /internal/users``), которым пользуется gamification при
  создании членства (решение А1,
  ``.claude/plans/05-admin-features.md``);
* чтение профильного имени пользователя
  (``GET /internal/users/{user_id}``), которым пользуется gamification,
  чтобы узнать имя, не владея email (план ``11-user-name``, этап 2).

Роутер лежит вне ``/users`` и потому недостижим снаружи по построению
(см. ``.claude/knowledge/07-routing.md``), а не по запрету в nginx.

Пользовательский JWT для межсервисной аутентификации не годится: users
проверяет вызывающего собственным служебным секретом
(``X-Service-Secret``), а предъявленный gamification ``subject_token`` —
доказательство того, что *пользователь* сам к ней обратился, а не
креденшел самой gamification.

Что users проверяет сам, а что принимает на веру (раздел 4.3 плана):

* сам — служебный секрет вызывающего; подпись, срок и отзыв
  ``subject_token``; существование и активность пользователя; формат
  ``role`` и остаток жизни токена;
* на веру — что ``sub`` действительно состоит в ``institution_id`` с
  ролью ``role``. Это ответственность gamification: у users больше нет
  хранилища членств, по которому это можно перепроверить.
"""

import hmac
import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Header, Response
from fastapi_users import exceptions as fastapi_users_exceptions
from fastapi_users.authentication.transport.bearer import BearerResponse
from gamification_auth import TokenError, decode_access_token
from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.api.deps import get_token_denylist, get_user_db, get_user_manager
from app.auth.backend import get_jwt_strategy
from app.auth.strategy import ClaimsJWTStrategy, key_value
from app.auth.user_manager import UserManager
from app.business.domain.entities import InstitutionContext
from app.business.domain.errors import (
    UserAlreadyExistsError as DomainUserAlreadyExistsError,
)
from app.business.domain.internal_errors import (
    PasswordRejectedError,
    ServiceAuthFailedError,
    SubjectTokenRejectedError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.core.config import Settings, get_settings
from app.repositories.denylist import TokenDenylist
from app.repositories.protocols import UserRepository
from app.schemas.user import FullName, UserCreate

logger = logging.getLogger(__name__)

# Формат роли, принесённой gamification. Словаря ролей в users нет
# (решение A1): проверяется только форма значения, состав допустимых
# ролей — забота gamification.
ROLE_PATTERN = r"^[a-z_]{1,32}$"


class InstitutionContextTokenRequest(BaseModel):
    """Тело запроса на выпуск токена в контексте учреждения.

    ``extra="forbid"``: лишнее поле в теле служебного вызова — признак
    рассинхронизации контракта, а не то, что можно молча проигнорировать.
    """

    model_config = ConfigDict(extra="forbid")

    subject_token: str
    institution_id: uuid.UUID
    role: str = Field(pattern=ROLE_PATTERN)


class InternalUserCreateRequest(BaseModel):
    """Тело запроса на заведение аккаунта с временным паролем.

    ``extra="forbid"`` — та же причина, что и у запроса выпуска токена:
    лишнее поле — признак рассинхронизации контракта.

    ``full_name`` — необязательное профильное имя (план 11-user-name,
    этап 2): gamification знает имя преподавателя раньше, чем он сам
    зайдёт и поправит его через ``PATCH /users/me``, и передаёт его при
    заведении аккаунта. Отсутствие поля (``None``) — обычный случай, имя
    не обязано быть известно заранее. Нормализуется тем же правилом,
    что и ``PATCH /users/me`` (``FullName``, решение владельца
    2026-10-12): пустая строка и строка из пробелов становятся
    ``None``, краевые пробелы у непустого имени срезаются.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str
    full_name: FullName


class InternalUserCreateResponse(BaseModel):
    """Ответ на успешное создание — только идентификатор.

    Ни email, ни пароль в ответ не возвращаются: вызывающий их и так
    знает, а лишнее эхо в ответе — лишний повод попасть в лог по пути.
    """

    id: uuid.UUID


class _InternalUserCreate(UserCreate):
    """``UserCreate`` с добавленным ``full_name`` — только для этого роутера.

    Отдельный класс, а не поле в самой ``UserCreate``: та схема
    используется и публичной регистрацией
    (``fastapi_users.get_register_router``), и расширять её контракт
    поводом внутреннего вызова не стоит. ``create_update_dict``
    наследуется без переопределения — ``full_name`` не входит в
    ``_PROTECTED_FIELDS``, поэтому проходит в ``user_dict`` как есть, и
    ``UserManager.create`` создаёт пользователя одной записью, как и
    остальные поля. Значение приходит сюда уже нормализованным
    ``InternalUserCreateRequest``, но поле объявлено тем же ``FullName``
    — не ради повторной нормализации, а чтобы не разводить контракт
    поля по двум схемам.
    """

    full_name: FullName


class InternalUserReadResponse(BaseModel):
    """Ответ на ``GET /internal/users/{user_id}`` — без email.

    Решение проекта: email в gamification не попадает ни в каком виде
    (план 11-user-name, этап 2) — gamification нужно только имя для
    отображения, а не персональные данные для связи.
    """

    id: uuid.UUID
    full_name: str | None


def _service_secret_matches(provided: str, secret: str) -> bool:
    """Сравнить секрет за постоянное время.

    Пустой ``secret`` никогда не совпадает — даже если ``provided`` тоже
    пуст: иначе в local/test с незаданным секретом любой запрос без
    заголовка проходил бы аутентификацию.
    """
    if not secret:
        return False
    return hmac.compare_digest(provided.encode(), secret.encode())


async def require_gamification_caller(
    x_service_secret: Annotated[str | None, Header()] = None,
) -> None:
    """Проверить служебный секрет вызывающего (зависимость роутера).

    Принимаются оба значения — текущее и ``_PREVIOUS`` — на время
    ротации секрета (развилка C, решение C1).
    """
    settings = get_settings()
    provided = x_service_secret or ""
    candidates = (
        settings.internal_gamification_secret,
        settings.internal_gamification_secret_previous,
    )
    if any(
        candidate is not None
        and _service_secret_matches(provided, candidate.get_secret_value())
        for candidate in candidates
    ):
        return
    raise ServiceAuthFailedError


async def _is_revoked_fail_open(denylist: TokenDenylist, token_id: str) -> bool:
    """Спросить denylist об отзыве, пропуская токен при его отказе.

    Тот же fail-open, что и в ``ClaimsJWTStrategy._is_revoked``: denylist
    недоступен рутинно и коротко, а ущерб от «пустить» ограничен сверху
    остатком TTL access-токена.
    """
    try:
        return await denylist.is_revoked(token_id)
    except Exception:
        logger.exception(
            "Token denylist is unavailable, accepting the subject token unchecked"
        )
        return False


def _new_token_id(token: str) -> str | None:
    """Достать ``jti`` только что выпущенного токена — для аудит-лога.

    Подпись не проверяется: токен выпущен этим же процессом мгновение
    назад, повторная проверка публичным ключом не добавляет доверия и
    стоит доли миллисекунды впустую.
    """
    return jwt.decode(token, options={"verify_signature": False}).get("jti")


router = APIRouter(dependencies=[Depends(require_gamification_caller)])


@router.post("/tokens/institution-context", response_model=BearerResponse)
async def issue_institution_context_token(
    payload: InstitutionContextTokenRequest,
    response: Response,
    strategy: Annotated[ClaimsJWTStrategy, Depends(get_jwt_strategy)],
    denylist: Annotated[TokenDenylist, Depends(get_token_denylist)],
    user_db: Annotated[UserRepository, Depends(get_user_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> BearerResponse:
    """Выпустить токен в контексте учреждения по запросу gamification.

    ``Cache-Control: no-store`` — тело содержит токен доступа, кешировать
    такой ответ нельзя нигде на пути.
    """
    try:
        claims = decode_access_token(
            payload.subject_token,
            public_key=key_value(strategy.decode_key),
            algorithms=[strategy.algorithm],
            audience=strategy.token_audience,
        )
    except TokenError:
        raise SubjectTokenRejectedError from None

    if claims.token_id is not None and await _is_revoked_fail_open(
        denylist, claims.token_id
    ):
        raise SubjectTokenRejectedError

    try:
        user_id = uuid.UUID(claims.subject)
    except ValueError:
        raise SubjectTokenRejectedError from None

    user = await user_db.get(user_id)
    if user is None or not user.is_active:
        raise SubjectTokenRejectedError

    remaining = int((claims.expires_at - datetime.now(tz=UTC)).total_seconds())
    lifetime_seconds = min(remaining, settings.jwt_lifetime_seconds)
    if lifetime_seconds <= 0:
        raise SubjectTokenRejectedError

    context = InstitutionContext(
        institution_id=payload.institution_id, role=payload.role
    )
    token = await strategy.write_token(user, context, lifetime_seconds=lifetime_seconds)

    # Аудит-лог выпуска: вызывающий, sub, institution_id, role, новый
    # jti. Сам токен сюда не попадает и не должен — ни в каком виде.
    logger.info(
        "Institution context token issued: caller=gamification sub=%s "
        "institution_id=%s role=%s jti=%s",
        claims.subject,
        payload.institution_id,
        payload.role,
        _new_token_id(token),
    )

    response.headers["Cache-Control"] = "no-store"
    return BearerResponse(access_token=token, token_type="bearer")


@router.post("/users", response_model=InternalUserCreateResponse, status_code=201)
async def create_internal_user(
    payload: InternalUserCreateRequest,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
) -> InternalUserCreateResponse:
    """Завести аккаунт с временным паролем по запросу gamification.

    Аккаунт создаётся через ``UserManager.create(..., safe=True,
    must_change_password=True)`` — тем же путём, что и публичная
    регистрация (валидация пароля по ``MIN_PASSWORD_LENGTH``, проверка
    занятого email, хеширование), одной записью: флаг вкладывается в тот
    же ``user_dict``, что и остальные поля, поэтому аккаунт не может на
    мгновение оказаться создан без него.

    Email существующего пользователя даёт тот же код независимо от
    регистра: уникальность по ``lower(email)`` обеспечивает хранилище
    (``ix_users_email_lower``), а библиотечная проверка в
    ``UserManager.create`` сравнивает тем же способом.

    ``full_name`` из тела запроса, если он есть, идёт в тот же
    ``user_dict`` — одной записью, как и остальные поля (``_InternalUserCreate``).
    """
    try:
        user = await user_manager.create(
            _InternalUserCreate(
                email=payload.email,
                password=payload.password,
                full_name=payload.full_name,
            ),
            safe=True,
            must_change_password=True,
        )
    except (
        fastapi_users_exceptions.UserAlreadyExists,
        DomainUserAlreadyExistsError,
    ):
        raise UserAlreadyExistsError from None
    except fastapi_users_exceptions.InvalidPasswordException:
        raise PasswordRejectedError from None

    # Аудит-лог: вызывающий и user_id. Ни email, ни пароль сюда не
    # попадают ни в каком виде, в том числе через текст исключения.
    logger.info("Internal user created: caller=gamification user_id=%s", user.id)

    return InternalUserCreateResponse(id=user.id)


@router.get("/users/{user_id}", response_model=InternalUserReadResponse)
async def get_internal_user(
    user_id: uuid.UUID,
    user_db: Annotated[UserRepository, Depends(get_user_db)],
) -> InternalUserReadResponse:
    """Отдать профильное имя пользователя по запросу gamification.

    Email в ответ не идёт ни в каком виде (решение проекта): gamification
    он не нужен и сознательно не передаётся — см. модульный докстринг.
    Поэтому ответ собирается явно по двум полям, а не из всей сущности
    ``User`` через ``from_attributes`` — так лишнее поле не может
    просочиться в контракт по ошибке при будущем добавлении поля в
    сущность.
    """
    user = await user_db.get(user_id)
    if user is None:
        raise UserNotFoundError

    return InternalUserReadResponse(id=user.id, full_name=user.full_name)
