"""Проверка access-токена.

Единственная точка, где сервис решает, доверять ли предъявленному
токену. Библиотека не ходит в сеть, не знает про HTTP и не поднимает
пользователя из хранилища — она только отвечает на вопрос «токен
настоящий и что в нём написано».
"""

from collections.abc import Sequence

import jwt

from gamification_auth.claims import REQUIRED_CLAIMS, AccessTokenClaims
from gamification_auth.errors import (
    TokenClaimsError,
    TokenExpiredError,
    TokenInvalidError,
)


def decode_access_token(
    token: str,
    *,
    public_key: str,
    algorithms: Sequence[str],
    audience: Sequence[str],
) -> AccessTokenClaims:
    """Проверить токен и вернуть его claims.

    ``algorithms`` передаётся вызывающим явным списком и **никогда** не
    берётся из заголовка самого токена. Иначе атакующий подставляет
    ``alg: HS256`` и подписывает токен публичным ключом как
    HMAC-секретом — публичный ключ известен всем (algorithm confusion).

    ``audience`` обязателен по той же причине, по которой обязателен
    ``exp``: токен, выпущенный для другой аудитории, не должен
    открывать наши эндпоинты.

    :raises TokenExpiredError: срок действия истёк.
    :raises TokenClaimsError: нет обязательного claim.
    :raises TokenInvalidError: подпись, аудитория, алгоритм или формат.
    """
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=list(algorithms),
            audience=list(audience),
            options={"require": list(REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError as error:
        raise TokenExpiredError("Срок действия токена истёк") from error
    except jwt.MissingRequiredClaimError as error:
        # Сюда же попадает отсутствующий ``aud``: PyJWT считает его
        # обязательным, когда аудитория передана на проверку.
        raise TokenClaimsError(
            f"В токене нет обязательного claim: {error.claim}"
        ) from error
    except jwt.PyJWTError as error:
        # Причина намеренно не детализируется: различать «неверная
        # подпись» и «чужая аудитория» полезно нам в логах, но не
        # предъявителю токена.
        raise TokenInvalidError("Токен не прошёл проверку") from error

    return AccessTokenClaims.from_payload(payload)
