"""SQLAlchemy-модели сервиса users.

Модели — деталь реализации хранилища, а не доменный слой: домен живёт в
``app.business.domain.entities`` и про SQLAlchemy не знает. Связь между ними
односторонняя и проверяемая — статическое присваивание в конце модуля
требует, чтобы модель удовлетворяла доменному протоколу, которым
типизирован весь прикладной код.

Учреждения и членства (``institutions``, ``memberships``) отсюда
удалены: они переехали в сервис gamification вместе с ролями и
статусами членства. Таблицы в базе users сносит миграция ``0002``.
"""

import uuid
from datetime import UTC, datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.user_protocol import AppUserProtocol
from app.repositories.database import Base


def _utcnow() -> datetime:
    """Текущий момент в UTC, осознанный по часовому поясу."""
    return datetime.now(UTC)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Пользователь платформы.

    ``id``, ``email``, ``hashed_password`` и три флага приходят из
    базового класса fastapi-users — переопределять их нельзя, на них
    завязан библиотечный адаптер. Имя таблицы задаётся своё: базовый
    класс объявляет ``user`` в единственном числе, а в схеме сервиса
    таблицы названы во множественном.

    ``created_at`` получает значение **на стороне Python**, а не через
    ``server_default``: библиотечный ``create`` возвращает объект сразу
    после вставки, и in-memory реализация тоже отдаёт заполненное поле.
    Серверный дефолт дал бы ``None`` до ``refresh`` и разошёлся бы с
    контрактом.
    """

    __tablename__ = "users"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    # Временный пароль, выданный админом учреждения через
    # ``POST /internal/users``. Снимается сменой пароля через
    # ``PATCH /users/me``. ``server_default`` — только для существующих
    # строк на момент миграции; новые пишутся с явным значением.
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false"), nullable=False
    )

    __table_args__ = (
        # Уникальность email без учёта регистра. Индекс с колонки
        # ``email``, приходящий из базового класса, регистрозависим:
        # ``a@b.c`` и ``A@B.C`` прошли бы оба, а ``get_by_email``
        # ищет через ``lower()`` и вернул бы произвольного из двух.
        # Проверка в коде адаптера от гонки не защищает — только индекс.
        # Оба индекса сосуществуют: библиотечный менять нельзя.
        Index("ix_users_email_lower", text("lower(email)"), unique=True),
    )


# Статическая проверка: модель обязана удовлетворять тому же доменному
# протоколу, что и in-memory сущность.
_USER_IMPLEMENTS_PROTOCOL: type[AppUserProtocol] = User


class RefreshSession(Base):
    """Refresh-сессия одного клиента (миграция ``0004``, план 10-refresh).

    ``client`` — ``web`` либо ``mobile`` (У4): путь предъявления
    refresh обязан совпадать с путём выдачи, поэтому тип клиента
    фиксируется здесь и больше не меняется.

    ``institution_id`` без внешнего ключа: gamification владеет
    учреждениями в собственной базе, у users нет таблицы, на которую
    можно было бы сослаться (та же причина, что убрала
    ``institutions``/``memberships`` из этой схемы в миграции ``0002``).
    """

    __tablename__ = "refresh_sessions"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    client: Mapped[str] = mapped_column(String(length=16), nullable=False)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(String(length=32), nullable=True)

    __table_args__ = (Index("ix_refresh_sessions_user_id", "user_id"),)


class RefreshToken(Base):
    """Один узел цепочки refresh-токенов (У1, У2).

    ``token_hash`` — SHA-256 сырого токена (``hex``, 64 символа), сам
    сырой токен в БД не хранится никогда. ``replaced_by_hash`` без
    внешнего ключа на себя же: строка-преемник создаётся в той же
    транзакции, что ссылка на неё, и ссылка на ещё не существующую
    строку не должна требовать отдельного порядка вставки.
    """

    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("refresh_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    replaced_by_hash: Mapped[str | None] = mapped_column(
        String(length=64), nullable=True
    )

    __table_args__ = (Index("ix_refresh_tokens_session_id", "session_id"),)
