"""Состояние in-memory хранилища сервиса users."""

import asyncio
import uuid
from dataclasses import dataclass, field

from app.business.domain.entities import RefreshSession, RefreshTokenRecord, User


@dataclass
class InMemoryUserStore:
    """Голое хранилище данных: словари и ничего больше.

    Состояние отделено от поведения намеренно: это повторяет будущую
    границу «сессия SQLAlchemy / адаптер». Здесь — аналог сессии
    (владелец данных и их времени жизни), в адаптере
    (``InMemoryUserDatabase``) — аналог операций над данными. При
    переходе на PostgreSQL этот класс заменяется на sessionmaker, а
    адаптер меняется независимо от него.

    Ключ ``email_index`` — всегда ``email.lower()``: так же, как
    работает уникальный индекс по ``lower(email)`` в БД.

    Учреждений и членств здесь больше нет: они переехали в gamification
    вместе с ролями и статусами.
    """

    users: dict[uuid.UUID, User] = field(default_factory=dict)
    email_index: dict[str, uuid.UUID] = field(default_factory=dict)

    def clear(self) -> None:
        """Очистить хранилище целиком."""
        self.users.clear()
        self.email_index.clear()


@dataclass
class InMemoryRefreshSessionStore:
    """Голое хранилище refresh-сессий и их токенов (план 10-refresh).

    Тот же принцип, что у ``InMemoryUserStore``: данные отдельно от
    поведения (в ``InMemoryRefreshSessionRepository``). ``locks`` — по
    одному ``asyncio.Lock`` на сессию, создаются лениво: без них два
    конкурентных ``rotate()`` для одной сессии могли бы переплестись
    между чтением и записью — то, что в PostgreSQL даёт ``SELECT ... FOR
    UPDATE``, здесь нужно эмулировать явно, так как один процесс не
    получает такой гарантии от самого event loop.
    """

    sessions: dict[uuid.UUID, RefreshSession] = field(default_factory=dict)
    tokens: dict[str, RefreshTokenRecord] = field(default_factory=dict)
    locks: dict[uuid.UUID, asyncio.Lock] = field(default_factory=dict)

    def lock_for(self, session_id: uuid.UUID) -> asyncio.Lock:
        """Вернуть (создав при необходимости) блокировку сессии."""
        lock = self.locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[session_id] = lock
        return lock

    def clear(self) -> None:
        """Очистить хранилище целиком."""
        self.sessions.clear()
        self.tokens.clear()
        self.locks.clear()
