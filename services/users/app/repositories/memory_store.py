"""Состояние in-memory хранилища сервиса users."""

import uuid
from dataclasses import dataclass, field

from app.business.domain.entities import User


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
