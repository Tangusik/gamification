"""Сущности доменного слоя сервиса users.

Слой не зависит от FastAPI, pydantic и SQLAlchemy — только stdlib.
Контракт пользователя, завязанный на библиотеку fastapi-users
(``AppUserProtocol``), сюда не входит: он лежит в ``app/auth/`` — слой
``business`` не имеет права импортировать каркасы.

Учреждения и членства (роль, статус) переехали в сервис gamification —
он стал источником истины о том, кто состоит в каком учреждении с какой
ролью. У users остаётся только личность (``User``) и **контекст**,
принесённый gamification при внутреннем выпуске токена
(``InstitutionContext``): users не хранит и не проверяет само членство,
а лишь переносит пару «учреждение + роль» в claims выпускаемого токена.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class User:
    """Пользователь платформы — конкретная сущность in-memory этапа.

    Хранит только личность и учётные флаги: роль и принадлежность к
    учреждению — не его дело, они принадлежат членству в gamification.

    ``must_change_password`` ставится при создании аккаунта с временным
    паролем (``POST /internal/users``) и снимается сменой пароля через
    ``PATCH /users/me``. Мягкий флаг: сервер запросы не блокирует, это
    дело клиента (решение C1).
    """

    id: uuid.UUID
    email: str
    hashed_password: str
    is_active: bool = True
    is_superuser: bool = False
    is_verified: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    must_change_password: bool = False


@dataclass(frozen=True)
class InstitutionContext:
    """Контекст учреждения, принесённый gamification при выпуске токена.

    Не сущность хранилища users — он не заводит, не хранит и не
    проверяет членства. Это просто пара значений, которую внутренний
    эндпоинт (``POST /internal/tokens/institution-context``) переносит
    в claims токена, приняв на веру от вызывающего сервиса.

    ``role`` — произвольная строка формата ``^[a-z_]{1,32}$``: словаря
    ролей в users нет (см. ``.claude/knowledge`` — решение A1), состав
    допустимых значений — забота gamification. Формат проверяется схемой
    запроса на границе API, а не здесь.
    """

    institution_id: uuid.UUID
    role: str
