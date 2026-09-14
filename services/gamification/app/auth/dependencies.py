"""Зависимость аутентификации: токен → ``Actor`` (раздел 3 плана).

Единственное место сервиса, где access-токен разбирается. Роль в
claims не читается — она принадлежит хранилищу членств, не токену.
"""

import logging
import uuid

from fastapi import Request
from gamification_auth import TokenError, decode_access_token

from app.auth.actor import Actor
from app.auth.denylist import TokenDenylistReader
from app.auth.errors import UnauthorizedError
from app.core.config import get_settings

logger = logging.getLogger(__name__)

_BEARER_PREFIX = "Bearer "


def _extract_bearer_token(header: str | None) -> str | None:
    """Достать токен из заголовка ``Authorization: Bearer <token>``."""
    if header is None or not header.startswith(_BEARER_PREFIX):
        return None
    token = header[len(_BEARER_PREFIX) :].strip()
    return token or None


async def get_current_actor(request: Request) -> Actor:
    """Проверить токен (подпись, срок, аудитория, отзыв) и вернуть ``Actor``.

    :raises UnauthorizedError: заголовка нет, токен не проходит проверку
        библиотеки ``gamification_auth`` или отозван по denylist users.
    """
    token = _extract_bearer_token(request.headers.get("Authorization"))
    if token is None:
        raise UnauthorizedError

    settings = get_settings()
    try:
        claims = decode_access_token(
            token,
            public_key=settings.jwt_public_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except TokenError:
        # Причина отказа не выносится наружу: подробности помогли бы
        # подбирать токен, транспорт всё равно отвечает 401.
        raise UnauthorizedError from None

    if claims.token_id is not None:
        reader: TokenDenylistReader = request.app.state.token_denylist_reader
        if await reader.is_revoked(claims.token_id):
            raise UnauthorizedError

    try:
        user_id = uuid.UUID(claims.subject)
    except ValueError:
        # Токен подписан users, поэтому нечитаемый sub — дефект выпуска,
        # а не действие клиента: он должен быть виден в логах.
        logger.warning("Token carries a malformed subject claim")
        raise UnauthorizedError from None

    institution_id: uuid.UUID | None = None
    if claims.institution_id is not None:
        try:
            institution_id = uuid.UUID(claims.institution_id)
        except ValueError:
            logger.warning("Token carries a malformed institution_id claim")

    return Actor(
        user_id=user_id,
        institution_id=institution_id,
        token_id=claims.token_id,
        raw_token=token,
    )
