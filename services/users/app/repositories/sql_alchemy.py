"""Адаптер хранилища поверх PostgreSQL.

Реализация того же контракта, что и in-memory
(``app.repositories.in_memory``): библиотечного ``BaseUserDatabase`` для
пользователей.

Общий принцип модуля: **нарушение уникальности приходит из БД, а не
проверяется заранее**. Предварительный SELECT не защищает от гонки — два
параллельных запроса пройдут проверку оба, — поэтому единственный
надёжный источник — ограничение в схеме. Цена: ``IntegrityError``
обязана быть поймана здесь и переведена в доменную ошибку. Не поймав её,
наружу отдали бы 500 вместо ``409 USER_ALREADY_EXISTS``, да ещё и с
сессией, требующей отката.

Сессия приходит извне и адаптеру не принадлежит: её жизненным циклом
управляет зависимость запроса (``app.api.deps``), одна на запрос.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_protocol import AppUserProtocol
from app.business.domain.errors import (
    DomainError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.repositories.models import User

# SQLSTATE нарушения уникального ограничения в PostgreSQL.
UNIQUE_VIOLATION = "23505"


def _is_unique_violation(error: IntegrityError) -> bool:
    """Отличить нарушение уникальности от прочих нарушений целостности.

    Разбирается именно SQLSTATE, а не текст ошибки: текст зависит от
    локали сервера и от имени ограничения. Нарушение внешнего ключа
    (``23503``) сюда не попадает и обязано лететь наружу как есть —
    это ошибка вызывающего кода, а не конфликт данных.

    Драйвер asyncpg прокидывается SQLAlchemy через обёртку, у которой
    ``sqlstate`` проставлен явно (см. ``_handle_exception`` в
    ``sqlalchemy.dialects.postgresql.asyncpg``), поэтому значение
    читается с ``error.orig``.
    """
    return getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION


@asynccontextmanager
async def _unique_violation_as(
    session: AsyncSession, domain_error: type[DomainError]
) -> AsyncIterator[None]:
    """Выполнить запись в SAVEPOINT, переведя конфликт в доменную ошибку.

    Почему SAVEPOINT, а не ``session.rollback()`` в обработчике: откат
    всей транзакции помечает просроченными **все** объекты сессии, а не
    только тот, что не записался. Сессия одна на запрос, поэтому
    прочитанный ранее пользователь после неудачной вставки превратился
    бы в мину: первое же обращение к его атрибуту вне ``await`` даёт
    ``MissingGreenlet`` — ошибка всплывает далеко от места, где возникла
    причина. Откат SAVEPOINT снимает только то, что сделано внутри
    блока.

    Проверять уникальность отдельным SELECT перед вставкой бесполезно:
    два параллельных запроса пройдут проверку оба. Единственный
    надёжный арбитр — ограничение в схеме.
    """
    try:
        async with session.begin_nested():
            yield
    except IntegrityError as error:
        if _is_unique_violation(error):
            raise domain_error from error
        raise


class SqlAlchemyUserRepository(SQLAlchemyUserDatabase[AppUserProtocol, uuid.UUID]):
    """Адаптер пользователей поверх библиотечного ``SQLAlchemyUserDatabase``.

    Переопределяется ровно то, что нужно контракту: чтение, удаление и
    OAuth-методы базового класса устраивают как есть. ``get_by_email``
    базового класса уже сравнивает через ``lower()`` — поиск без учёта
    регистра приходит бесплатно, а уникальность того же ``lower(email)``
    обеспечена функциональным индексом в схеме.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, User)

    async def create(self, create_dict: dict[str, Any]) -> AppUserProtocol:
        """Создать пользователя.

        Тело повторяет библиотечный ``create`` (add + commit + refresh),
        но вставка идёт внутри SAVEPOINT: делегировать в ``super()`` и
        ловить ошибку снаружи нельзя — к тому моменту транзакция уже
        оборвана и спасать сессию поздно.

        :raises UserAlreadyExistsError: email занят — точным совпадением
            или отличающимся регистром, оба индекса дают один SQLSTATE.
        """
        user = self.user_table(**create_dict)
        async with _unique_violation_as(self.session, UserAlreadyExistsError):
            self.session.add(user)

        await self.session.commit()
        await self.session.refresh(user)
        return user

    async def update(
        self, user: AppUserProtocol, update_dict: dict[str, Any]
    ) -> AppUserProtocol:
        """Обновить пользователя, найденного по ``user.id``.

        Существование проверяется до записи, как в in-memory: иначе
        обновление удалённой записи молча вставило бы её заново.

        :raises UserNotFoundError: записи с таким ``id`` нет.
        :raises UserAlreadyExistsError: новый email занят.
        """
        if await self.session.get(User, user.id) is None:
            raise UserNotFoundError

        async with _unique_violation_as(self.session, UserAlreadyExistsError):
            for key, value in update_dict.items():
                setattr(user, key, value)
            self.session.add(user)

        await self.session.commit()
        await self.session.refresh(user)
        return user
