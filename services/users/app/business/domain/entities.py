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

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Клиенты, для которых заводится refresh-сессия (У4, вопрос 6). Путь
# предъявления обязан совпадать с путём выдачи: веб — только cookie,
# мобильный — только тело запроса.
CLIENT_WEB = "web"
CLIENT_MOBILE = "mobile"


def generate_refresh_token() -> str:
    """Сгенерировать сырой refresh-токен.

    ``secrets.token_urlsafe(32)`` даёт 256 бит энтропии — соль при
    хешировании не нужна (У1): подобрать по хешу нечем.
    """
    return secrets.token_urlsafe(32)


def hash_refresh_token(raw_token: str) -> str:
    """Захешировать сырой refresh-токен для хранения (У1).

    Сырой токен в БД и в логах не хранится никогда — только этот хеш.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


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


@dataclass
class RefreshSession:
    """Refresh-сессия одного клиента (У1, план 10-refresh).

    Одна сессия — одна цепочка refresh-токенов одного клиента
    (``web``/``mobile``) одного пользователя. Путь предъявления обязан
    совпадать с путём выдачи (У4): сессия ``web`` живёт только в
    cookie, ``mobile`` — только в теле запроса.

    ``institution_id`` — последнее подтверждённое gamification
    учреждение (вопрос 1 = А). ``None`` — учреждение ещё не выбрано или
    membership-проверка вернула 404.

    ``idle_expires_at`` — скользящее окно простоя, отодвигается каждой
    успешной ротацией. ``absolute_expires_at`` фиксируется при создании
    сессии и не продлевается никогда — оба предела заданы отдельными
    настройками на клиента (вопрос 4 = Б).
    """

    id: uuid.UUID
    user_id: uuid.UUID
    client: str
    institution_id: uuid.UUID | None
    created_at: datetime
    last_used_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None = None
    revoke_reason: str | None = None

    @property
    def is_revoked(self) -> bool:
        """Погашена ли сессия — явно или по любой другой причине."""
        return self.revoked_at is not None

    def is_expired(self, *, now: datetime) -> bool:
        """Истёк ли один из двух пределов жизни сессии."""
        return self.absolute_expires_at <= now or self.idle_expires_at <= now


@dataclass
class RefreshTokenRecord:
    """Один узел цепочки refresh-токенов сессии (У1).

    Хранится вся цепочка, а не только предыдущий токен: без этого вор,
    дважды провернувший ротацию, остаётся незамеченным, когда легитимный
    пользователь предъявит старый токен (У2).
    """

    token_hash: str
    session_id: uuid.UUID
    created_at: datetime
    used_at: datetime | None = None
    replaced_by_hash: str | None = None
