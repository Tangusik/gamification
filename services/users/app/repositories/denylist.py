"""Denylist отозванных токенов: контракт и две реализации.

Отзыв адресует токены по ``jti``, а не по их телу: иначе один и тот же
токен, предъявленный с другим представлением, остался бы живым, а
погасить сессию целиком было бы нечем.

Запись живёт ровно до истечения самого токена (**TTL = ``exp - now``**,
не больше): тогда denylist самоочищается и не растёт — хранить отзыв
дольше, чем действует токен, бессмысленно.

Реализация в памяти существует по той же причине, что и in-memory
хранилище пользователей: тесты выхода из системы не должны требовать
поднятого Redis. В нескольких репликах она непригодна — отзыв увидит
только тот процесс, который его записал.

Решение о поведении при недоступности denylist (**fail-open**) принято
владельцем проекта и живёт не здесь, а в ``app.auth.strategy``: это
свойство проверки токена, а не хранилища. Методы ниже честно
пробрасывают ошибку наружу.

Формат ключа (``users:denylist:jti:<jti>``) — общий контракт между
``users`` (пишет отзыв при выходе) и остальными сервисами (читают его
только на чтение, fail-open), поэтому он живёт в ``gamification_auth``,
а не здесь: разъехавшись, denylist работал бы только частично, пока это
не было бы замечено.
"""

import logging
import time
from typing import Protocol

from gamification_auth import denylist_key
from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)

# Значение ключа не несёт смысла: важен сам факт присутствия. Пишется
# самое короткое, потому что таких ключей может быть много.
_REVOKED = "1"

# Сколько ждать Redis. Без таймаута недоступный (но не отказывающий в
# соединении) сервер держал бы запрос до таймаута сокета по умолчанию —
# fail-open превратился бы в зависание вместо мгновенного пропуска.
_SOCKET_TIMEOUT_SECONDS = 1.0


class TokenDenylist(Protocol):
    """Хранилище отозванных токенов.

    Контракт намеренно узкий: положить ``jti`` на ограниченный срок,
    спросить про ``jti``, ответить на пробу готовности и закрыться.
    """

    async def revoke(self, token_id: str, ttl_seconds: int) -> None:
        """Отозвать токен на ``ttl_seconds`` секунд.

        Неположительный ``ttl_seconds`` означает уже истёкший токен:
        запись не делается — гасить нечего.
        """
        ...

    async def is_revoked(self, token_id: str) -> bool:
        """Ответить, отозван ли токен с таким ``jti``."""
        ...

    async def ping(self) -> bool:
        """Проверить доступность хранилища для пробы готовности."""
        ...

    async def close(self) -> None:
        """Освободить ресурсы; вызывается в ``lifespan``."""
        ...


def create_redis_client(url: str) -> Redis:
    """Создать клиент Redis для указанного URL.

    Как и в ``app.repositories.database``, настройки здесь не читаются:
    URL приходит аргументом, поэтому один и тот же код собирает клиент и
    в рантайме сервиса, и в тестах.
    """
    return Redis.from_url(
        url,
        socket_timeout=_SOCKET_TIMEOUT_SECONDS,
        socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
    )


class RedisTokenDenylist:
    """Denylist поверх Redis: ключ на ``jti`` с истечением по TTL.

    Срок жизни задаётся самой записи (``SET ... EX``), а не проверяется
    при чтении: чистить хранилище отдельным процессом не нужно, и
    забытая запись не может пережить токен.
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def revoke(self, token_id: str, ttl_seconds: int) -> None:
        """Записать отзыв на остаток жизни токена."""
        if ttl_seconds <= 0:
            return
        await self._client.set(denylist_key(token_id), _REVOKED, ex=ttl_seconds)

    async def is_revoked(self, token_id: str) -> bool:
        """Проверить наличие ключа отзыва."""
        return bool(await self._client.exists(denylist_key(token_id)))

    async def ping(self) -> bool:
        """Выполнить ``PING``; недоступность — это ``False``, не отказ.

        Ошибка не пробрасывается, потому что единственный вызывающий —
        проба готовности: ей нужен ответ «да/нет», а не исключение.
        """
        try:
            await self._client.ping()
        except (RedisError, OSError):
            logger.exception("Token denylist is unavailable")
            return False
        return True

    async def close(self) -> None:
        """Закрыть клиент вместе с его пулом соединений."""
        await self._client.aclose()


class InMemoryTokenDenylist:
    """Denylist в памяти процесса — тестовый дублёр Redis-реализации.

    Истечение считается по монотонным часам: системное время может
    прыгнуть назад, и тогда отзыв ожил бы раньше срока.
    """

    def __init__(self) -> None:
        self._deadlines: dict[str, float] = {}

    async def revoke(self, token_id: str, ttl_seconds: int) -> None:
        """Запомнить отзыв до момента ``сейчас + ttl_seconds``."""
        if ttl_seconds <= 0:
            return
        self._deadlines[token_id] = time.monotonic() + ttl_seconds

    async def is_revoked(self, token_id: str) -> bool:
        """Проверить отзыв, попутно выбросив истёкшую запись.

        Чистка при чтении заменяет TTL хранилища: без неё словарь рос бы
        до конца жизни процесса.
        """
        deadline = self._deadlines.get(token_id)
        if deadline is None:
            return False
        if deadline <= time.monotonic():
            del self._deadlines[token_id]
            return False
        return True

    async def ping(self) -> bool:
        """Хранилище живёт в процессе: отвечает всегда."""
        return True

    async def close(self) -> None:
        """Освобождать нечего."""
        return None
