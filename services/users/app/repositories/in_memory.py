"""In-memory реализация адаптера пользователей сервиса users.

Поведение намеренно повторяет ``SQLAlchemyUserDatabase`` из
``fastapi_users_db_sqlalchemy``, чтобы переход на PostgreSQL не менял
наблюдаемый контракт.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi_users.db import BaseUserDatabase

from app.auth.user_protocol import AppUserProtocol
from app.business.domain.entities import RefreshSession as DomainRefreshSession
from app.business.domain.entities import (
    RefreshTokenRecord,
    User,
    generate_refresh_token,
    hash_refresh_token,
)
from app.business.domain.errors import UserAlreadyExistsError, UserNotFoundError
from app.repositories.memory_store import InMemoryRefreshSessionStore, InMemoryUserStore
from app.repositories.protocols import RotationOutcome, RotationResult


class InMemoryUserDatabase(BaseUserDatabase[AppUserProtocol, uuid.UUID]):
    """Адаптер fastapi-users поверх словарей ``InMemoryUserStore``.

    Все читающие методы возвращают **копию** сущности, а не объект из
    словаря. Иначе вызывающий получил бы ссылку на хранимую запись и
    мог бы изменить её мимо ``update``, тогда как адаптер PostgreSQL
    вернёт объект сессии. Без копий тесты незаметно начали бы зависеть
    от алиасинга, и первый же переход на БД дал бы расхождение
    поведения.

    OAuth-методы (``get_by_oauth_account``, ``add_oauth_account``,
    ``update_oauth_account``) не переопределяются: базовый класс уже
    поднимает ``NotImplementedError``, что и требуется на этом этапе.
    При подключении OAuth-провайдеров их нужно реализовать здесь.
    """

    def __init__(self, store: InMemoryUserStore) -> None:
        self._store = store

    async def get(self, id: uuid.UUID) -> AppUserProtocol | None:
        """Вернуть пользователя по идентификатору или ``None``."""
        user = self._store.users.get(id)
        return replace(user) if user is not None else None

    async def get_by_email(self, email: str) -> AppUserProtocol | None:
        """Вернуть пользователя по email без учёта регистра."""
        user_id = self._store.email_index.get(email.lower())
        if user_id is None:
            return None
        user = self._store.users.get(user_id)
        return replace(user) if user is not None else None

    async def create(self, create_dict: dict[str, Any]) -> AppUserProtocol:
        """Создать пользователя из словаря полей сущности.

        Словарь распаковывается в конструктор ``User`` напрямую, как это
        делает SQLAlchemy-адаптер: неизвестный ключ обязан приводить к
        ошибке, а не проглатываться молча. Значения по умолчанию
        (``is_active``, ``is_verified``, ``is_superuser``,
        ``created_at``) берутся из dataclass.
        """
        user = User(id=uuid.uuid4(), **create_dict)
        if user.email.lower() in self._store.email_index:
            raise UserAlreadyExistsError

        self._store.users[user.id] = user
        self._store.email_index[user.email.lower()] = user.id
        return replace(user)

    async def update(
        self, user: AppUserProtocol, update_dict: dict[str, Any]
    ) -> AppUserProtocol:
        """Обновить поля пользователя, найденного по ``user.id``.

        Переданный ``user`` — копия, полученная ранее из адаптера,
        поэтому мутировать его бессмысленно: изменяется хранимая запись.
        """
        stored = self._store.users.get(user.id)
        if stored is None:
            raise UserNotFoundError

        new_email = update_dict.get("email")
        if new_email is not None and new_email.lower() != stored.email.lower():
            owner_id = self._store.email_index.get(new_email.lower())
            if owner_id is not None and owner_id != stored.id:
                raise UserAlreadyExistsError

        old_email_key = stored.email.lower()
        for key, value in update_dict.items():
            setattr(stored, key, value)

        if stored.email.lower() != old_email_key:
            self._store.email_index.pop(old_email_key, None)
            self._store.email_index[stored.email.lower()] = stored.id

        return replace(stored)

    async def delete(self, user: AppUserProtocol) -> None:
        """Удалить пользователя; отсутствие записи ошибкой не считается.

        Email для чистки индекса берётся из хранимой записи, а не из
        переданной копии: копия могла устареть после смены email.
        """
        stored = self._store.users.pop(user.id, None)
        if stored is not None:
            self._store.email_index.pop(stored.email.lower(), None)


class InMemoryRefreshSessionRepository:
    """In-memory реализация refresh-сессий (план 10-refresh).

    Ротация сериализуется явной блокировкой на сессию
    (``InMemoryRefreshSessionStore.lock_for``): один процесс не даёт
    такой гарантии от event loop даром, а поведение обязано совпадать с
    SQL-реализацией (``SELECT ... FOR UPDATE``) — оттуда же одинаковый
    исход гонки двух refresh одним токеном.

    Grace-окно (вопрос 3 = А) вытесняет прежнего преемника, но **не
    удаляет** его запись (H1, ревью Ч3, исправлено 2026-09-15): он
    помечается использованным без собственного преемника, и его
    предъявление уходит в ветку повтора, гася всю сессию целиком —
    см. докстринг ``SqlAlchemyRefreshSessionRepository`` за подробностями.
    """

    def __init__(self, store: InMemoryRefreshSessionStore) -> None:
        self._store = store

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
        session = DomainRefreshSession(
            id=uuid.uuid4(),
            user_id=user_id,
            client=client,
            institution_id=institution_id,
            created_at=now,
            last_used_at=now,
            idle_expires_at=now + idle_ttl,
            absolute_expires_at=now + absolute_ttl,
        )
        self._store.sessions[session.id] = session

        raw_token = generate_refresh_token()
        token_hash = hash_refresh_token(raw_token)
        self._store.tokens[token_hash] = RefreshTokenRecord(
            token_hash=token_hash, session_id=session.id, created_at=now
        )
        return replace(session), raw_token

    async def find(self, token_hash: str) -> DomainRefreshSession | None:
        """См. ``RefreshSessionRepository.find``."""
        token = self._store.tokens.get(token_hash)
        if token is None:
            return None
        session = self._store.sessions.get(token.session_id)
        if session is None:
            return None
        return replace(session)

    async def rotate(
        self,
        *,
        token_hash: str,
        idle_ttl: timedelta,
        reuse_grace: timedelta,
        institution_id: uuid.UUID | None,
    ) -> RotationResult:
        """См. ``RefreshSessionRepository.rotate``."""
        token = self._store.tokens.get(token_hash)
        if token is None:
            return RotationResult(RotationOutcome.NOT_FOUND)

        async with self._store.lock_for(token.session_id):
            # Освежить под блокировкой: конкурентная ротация могла уже
            # изменить обе записи, пока мы ждали lock.
            token = self._store.tokens.get(token_hash)
            if token is None:
                return RotationResult(RotationOutcome.NOT_FOUND)
            session = self._store.sessions.get(token.session_id)
            if session is None or session.revoked_at is not None:
                return RotationResult(RotationOutcome.NOT_FOUND)

            now = datetime.now(UTC)
            if session.absolute_expires_at <= now or session.idle_expires_at <= now:
                return RotationResult(RotationOutcome.NOT_FOUND)

            new_raw = generate_refresh_token()
            new_hash = hash_refresh_token(new_raw)

            if token.used_at is None:
                token.used_at = now
                token.replaced_by_hash = new_hash
                self._store.tokens[new_hash] = RefreshTokenRecord(
                    token_hash=new_hash, session_id=session.id, created_at=now
                )
                session.last_used_at = now
                session.idle_expires_at = now + idle_ttl
                session.institution_id = institution_id
                return RotationResult(
                    RotationOutcome.ROTATED, replace(session), new_raw
                )

            successor = (
                self._store.tokens.get(token.replaced_by_hash)
                if token.replaced_by_hash is not None
                else None
            )
            within_grace = (now - token.used_at) <= reuse_grace
            if successor is not None and successor.used_at is None and within_grace:
                # Преемник не удаляется (H1, ревью Ч3): помечается
                # использованным без собственного преемника, поэтому его
                # предъявление позже попадёт в ветку ниже и погасит сессию.
                successor.used_at = now
                token.replaced_by_hash = new_hash
                self._store.tokens[new_hash] = RefreshTokenRecord(
                    token_hash=new_hash, session_id=session.id, created_at=now
                )
                session.last_used_at = now
                session.idle_expires_at = now + idle_ttl
                session.institution_id = institution_id
                return RotationResult(
                    RotationOutcome.ROTATED, replace(session), new_raw
                )

            session.revoked_at = now
            session.revoke_reason = "reuse"
            return RotationResult(RotationOutcome.REUSED, replace(session))

    async def release(self) -> None:
        """См. ``RefreshSessionRepository.release``.

        No-op: in-memory хранилище не открывает отдельной транзакции,
        закрывать нечего.
        """

    async def revoke(self, session_id: uuid.UUID, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke``."""
        session = self._store.sessions.get(session_id)
        if session is None:
            return
        session.revoked_at = datetime.now(UTC)
        session.revoke_reason = reason

    async def revoke_for_user(self, user_id: uuid.UUID, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke_for_user``."""
        now = datetime.now(UTC)
        for session in self._store.sessions.values():
            if session.user_id == user_id and session.revoked_at is None:
                session.revoked_at = now
                session.revoke_reason = reason

    async def revoke_by_token(self, token_hash: str, *, reason: str) -> None:
        """См. ``RefreshSessionRepository.revoke_by_token``."""
        token = self._store.tokens.get(token_hash)
        if token is None:
            return
        await self.revoke(token.session_id, reason=reason)

    async def delete_expired_for_user(self, user_id: uuid.UUID) -> None:
        """См. ``RefreshSessionRepository.delete_expired_for_user``."""
        now = datetime.now(UTC)
        expired_ids = {
            session_id
            for session_id, session in self._store.sessions.items()
            if session.user_id == user_id
            and (session.absolute_expires_at <= now or session.idle_expires_at <= now)
        }
        for session_id in expired_ids:
            del self._store.sessions[session_id]
        for token_hash in [
            th
            for th, tok in self._store.tokens.items()
            if tok.session_id in expired_ids
        ]:
            del self._store.tokens[token_hash]
