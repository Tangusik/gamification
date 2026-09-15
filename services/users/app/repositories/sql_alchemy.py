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
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy import delete, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.user_protocol import AppUserProtocol
from app.business.domain.entities import RefreshSession as DomainRefreshSession
from app.business.domain.entities import generate_refresh_token, hash_refresh_token
from app.business.domain.errors import (
    DomainError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from app.repositories.models import RefreshSession, RefreshToken, User
from app.repositories.protocols import RotationOutcome, RotationResult

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


def _session_to_domain(row: RefreshSession) -> DomainRefreshSession:
    """Собрать доменную сущность сессии из строки SQLAlchemy."""
    return DomainRefreshSession(
        id=row.id,
        user_id=row.user_id,
        client=row.client,
        institution_id=row.institution_id,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        idle_expires_at=row.idle_expires_at,
        absolute_expires_at=row.absolute_expires_at,
        revoked_at=row.revoked_at,
        revoke_reason=row.revoke_reason,
    )


class SqlAlchemyRefreshSessionRepository:
    """Адаптер refresh-сессий поверх PostgreSQL (У1, У2, план 10-refresh).

    Атомарность ротации обеспечивается блокировкой строки сессии
    (``SELECT ... FOR UPDATE``): она сериализует конкурентные refresh
    одной сессии, поэтому обе развилки — «два refresh одним токеном» и
    «grace-окно после потерянного ответа» (вопрос 3) — разрешаются одним
    и тем же кодом ниже. Условная ``UPDATE ... WHERE used_at IS NULL``
    оставлена как защитный дубль на случай изменения этой блокировки в
    будущем, а не потому что она обязательна при нынешней сериализации.

    Grace-окно (вопрос 3 = А) вытесняет прежнего преемника, но **не
    удаляет** его строку (H1, ревью Ч3, исправлено 2026-09-15): он
    помечается использованным без собственного преемника. Его
    предъявление после этого — не «неизвестный токен» с тихим 401, а
    настоящий повтор: ветка ``REUSED`` гасит всю сессию целиком, включая
    токен, выигравший гонку. Цена принята владельцем — гонка двух вкладок
    без Web Locks (риск 1 плана) тоже гасит сессию.

    Сессия приходит извне, как и у ``SqlAlchemyUserRepository``; каждый
    метод коммитит её сам — тот же стиль, что и у пользователей.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        client: str,
        institution_id: uuid.UUID | None,
        idle_ttl: timedelta,
        absolute_ttl: timedelta,
    ) -> tuple[DomainRefreshSession, str]:
        """См. ``RefreshSessionRepository.create``."""
        now = datetime.now(UTC)
        session_row = RefreshSession(
            id=uuid.uuid4(),
            user_id=user_id,
            client=client,
            institution_id=institution_id,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now + idle_ttl,
            absolute_expires_at=now + absolute_ttl,
        )
        self.session.add(session_row)
        await self.session.flush()

        raw_token = generate_refresh_token()
        self.session.add(
            RefreshToken(
                token_hash=hash_refresh_token(raw_token),
                session_id=session_row.id,
                created_at=now,
            )
        )
        await self.session.commit()
        await self.session.refresh(session_row)
        return _session_to_domain(session_row), raw_token

    async def find(self, token_hash: str) -> DomainRefreshSession | None:
        """См. ``RefreshSessionRepository.find``."""
        token_row = await self.session.get(RefreshToken, token_hash)
        if token_row is None:
            return None
        session_row = await self.session.get(RefreshSession, token_row.session_id)
        if session_row is None:
            return None
        return _session_to_domain(session_row)

    async def release(self) -> None:
        """См. ``RefreshSessionRepository.release``.

        ``commit()``, а не ``rollback()``: транзакция только читала, а
        фабрика сессий собрана с ``expire_on_commit=False``
        (``app.repositories.database``), поэтому уже загруженные объекты
        (например, пользователь, прочитанный роутером для проверки
        ``is_active``) остаются пригодными к использованию после вызова
        без похода в БД. ``rollback()`` того же эффекта не даёт: он
        помечает объекты сессии просроченными независимо от
        ``expire_on_commit``.
        """
        await self.session.commit()

    async def rotate(
        self,
        *,
        token_hash: str,
        idle_ttl: timedelta,
        reuse_grace: timedelta,
        institution_id: uuid.UUID | None,
    ) -> RotationResult:
        """См. ``RefreshSessionRepository.rotate``."""
        now = datetime.now(UTC)

        token_row = await self.session.get(RefreshToken, token_hash)
        if token_row is None:
            await self.session.rollback()
            return RotationResult(RotationOutcome.NOT_FOUND)

        # Блокировка сессии сериализует конкурентные ротации одной и той
        # же сессии — из неё рождается детерминированный исход гонки
        # двух refresh одним токеном.
        #
        # ``populate_existing=True`` обязателен вместе с ``with_for_update``
        # (L1, ревью Ч3): без него ``Session.get`` для строки, уже
        # лежащей в identity map (``find`` перед вызовом ротации в том же
        # запросе), вернул бы кешированный объект без блокировки и без
        # перечитывания ``revoked_at`` — logout или смена пароля,
        # случившиеся между чтением и ротацией, остались бы незамеченными.
        session_row = await self.session.get(
            RefreshSession,
            token_row.session_id,
            with_for_update=True,
            populate_existing=True,
        )
        if session_row is None or session_row.revoked_at is not None:
            await self.session.rollback()
            return RotationResult(RotationOutcome.NOT_FOUND)
        if session_row.absolute_expires_at <= now or session_row.idle_expires_at <= now:
            await self.session.rollback()
            return RotationResult(RotationOutcome.NOT_FOUND)

        # Освежить токен под блокировкой сессии: конкурентная ротация
        # могла завершиться, пока мы ждали lock.
        await self.session.refresh(token_row)

        new_raw = generate_refresh_token()
        new_hash = hash_refresh_token(new_raw)

        if token_row.used_at is None:
            claim = await self.session.execute(
                update(RefreshToken)
                .where(
                    RefreshToken.token_hash == token_hash,
                    RefreshToken.used_at.is_(None),
                )
                .values(used_at=now, replaced_by_hash=new_hash)
            )
            if claim.rowcount == 1:
                self.session.add(
                    RefreshToken(
                        token_hash=new_hash,
                        session_id=session_row.id,
                        created_at=now,
                    )
                )
                session_row.last_used_at = now
                session_row.idle_expires_at = now + idle_ttl
                session_row.institution_id = institution_id
                await self.session.commit()
                await self.session.refresh(session_row)
                return RotationResult(
                    RotationOutcome.ROTATED, _session_to_domain(session_row), new_raw
                )
            await self.session.refresh(token_row)

        # ``used_at`` заполнен: либо grace, либо настоящий повтор.
        successor = None
        if token_row.replaced_by_hash is not None:
            successor = await self.session.get(RefreshToken, token_row.replaced_by_hash)

        within_grace = (
            token_row.used_at is not None and (now - token_row.used_at) <= reuse_grace
        )
        if successor is not None and successor.used_at is None and within_grace:
            # Преемник не удаляется (H1, ревью Ч3): его предъявление
            # обязано погасить сессию, а не тихо получить 401 неизвестного
            # токена. ``replaced_by_hash`` у него остаётся пустым — при
            # предъявлении он попадёт в ветку ниже (``used_at`` уже не
            # ``None``, преемника у него нет) и уйдёт в ``REUSED``.
            successor.used_at = now
            token_row.replaced_by_hash = new_hash
            self.session.add(
                RefreshToken(
                    token_hash=new_hash, session_id=session_row.id, created_at=now
                )
            )
            session_row.last_used_at = now
            session_row.idle_expires_at = now + idle_ttl
            session_row.institution_id = institution_id
            await self.session.commit()
            await self.session.refresh(session_row)
            return RotationResult(
                RotationOutcome.ROTATED, _session_to_domain(session_row), new_raw
            )

        session_row.revoked_at = now
        session_row.revoke_reason = "reuse"
        await self.session.commit()
        await self.session.refresh(session_row)
        return RotationResult(RotationOutcome.REUSED, _session_to_domain(session_row))

    async def revoke(self, session_id: uuid.UUID, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke``."""
        session_row = await self.session.get(RefreshSession, session_id)
        if session_row is None:
            return
        session_row.revoked_at = datetime.now(UTC)
        session_row.revoke_reason = reason
        await self.session.commit()

    async def revoke_for_user(self, user_id: uuid.UUID, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke_for_user``."""
        await self.session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
            )
            .values(revoked_at=datetime.now(UTC), revoke_reason=reason)
        )
        await self.session.commit()

    async def revoke_by_token(self, token_hash: str, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke_by_token``."""
        token_row = await self.session.get(RefreshToken, token_hash)
        if token_row is None:
            return
        await self.revoke(token_row.session_id, reason=reason)

    async def delete_expired_for_user(self, user_id: uuid.UUID) -> None:
        """См. ``RefreshSessionRepository.delete_expired_for_user``."""
        now = datetime.now(UTC)
        await self.session.execute(
            delete(RefreshSession).where(
                RefreshSession.user_id == user_id,
                or_(
                    RefreshSession.absolute_expires_at <= now,
                    RefreshSession.idle_expires_at <= now,
                ),
            )
        )
        await self.session.commit()
