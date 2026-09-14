"""Проверка access-токенов платформы геймификации.

Библиотека умеренно мала намеренно: она отвечает ровно за то, что не
имеет права разъехаться между сервисами, — формат токена и правила его
проверки. Доменной логики, обращений к БД и знания про HTTP здесь нет
и быть не должно.

Выпускает токены только сервис ``users``; все остальные сервисы
проверяют их локально по публичному ключу, не обращаясь к ``users`` на
каждый запрос.

Применение::

    from gamification_auth import decode_access_token, TokenError

    try:
        claims = decode_access_token(
            token,
            public_key=settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
            audience=["fastapi-users:auth"],
        )
    except TokenError:
        ...  # перевод в HTTP-ответ — задача сервиса
"""

from gamification_auth.claims import REQUIRED_CLAIMS, AccessTokenClaims
from gamification_auth.denylist import denylist_key
from gamification_auth.errors import (
    TokenClaimsError,
    TokenError,
    TokenExpiredError,
    TokenInvalidError,
)
from gamification_auth.verify import decode_access_token

__all__ = [
    "REQUIRED_CLAIMS",
    "AccessTokenClaims",
    "TokenClaimsError",
    "TokenError",
    "TokenExpiredError",
    "TokenInvalidError",
    "decode_access_token",
    "denylist_key",
]
