"""Чтение denylist отозванных токенов users (K1).

Gamification не выпускает токены и потому не пишет отзыв — только
читает его: пользователь мог выйти из системы через users, и его токен
обязан перестать приниматься и здесь. Проверка **fail-open** и
работает с таймаутом 1 с — те же правила, что в
``services/users/app/repositories/denylist.py``, только без записи.
Недоступность отражается в readiness (``probe_denylist``), но не
отвергает запросы.
"""

import logging
from typing import Protocol

from gamification_auth import denylist_key
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

_SOCKET_TIMEOUT_SECONDS = 1.0


class TokenDenylistReader(Protocol):
    """Только чтение: gamification не имеет права отзывать чужие токены."""

    async def is_revoked(self, token_id: str) -> bool:
        """Ответить, отозван ли токен с таким ``jti``."""
        ...

    async def ping(self) -> bool:
        """Проверить доступность для пробы готовности."""
        ...

    async def close(self) -> None:
        """Освободить ресурсы; вызывается в ``lifespan``."""
        ...


def create_redis_client(url: str) -> Redis:
    """Создать клиент Redis для указанного URL."""
    return Redis.from_url(
        url,
        socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
    )


class RedisTokenDenylistReader:
    """Denylist поверх Redis users: только ``EXISTS``, ничего не пишет."""

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def is_revoked(self, token_id: str) -> bool:
        """Fail-open: недоступность Redis не отклоняет запрос.

        Тот же принцип, что и в стратегии users — молчаливый fail-open
        неотличим от работающего отзыва, поэтому уровень лога ``error``.
        """
        try:
            return bool(await self._client.exists(denylist_key(token_id)))
        except (RedisError, OSError):
            logger.exception(
                "Token denylist is unavailable, accepting the token unchecked"
            )
            return False

    async def ping(self) -> bool:
        """Выполнить ``PING``; недоступность — ``False``, не отказ."""
        try:
            await self._client.ping()
        except (RedisError, OSError):
            logger.exception("Token denylist is unavailable")
            return False
        return True

    async def close(self) -> None:
        """Закрыть клиент вместе с его пулом соединений."""
        await self._client.aclose()


class NullTokenDenylistReader:
    """Denylist не настроен: пустой ``GAMIFICATION_REDIS_URL`` (local/test).

    Отзыв в этом режиме не проверяется вовсе — так же, как и denylist в
    памяти сервиса users не виден второй реплике. Проба готовности
    всегда ``True``: незаданная зависимость — не то же самое, что
    недоступная.
    """

    async def is_revoked(self, token_id: str) -> bool:
        return False

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None
