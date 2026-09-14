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

from datetime import UTC, datetime

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from sqlalchemy import Boolean, DateTime, Index, text
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
