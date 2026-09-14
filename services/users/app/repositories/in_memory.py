"""In-memory реализация адаптера пользователей сервиса users.

Поведение намеренно повторяет ``SQLAlchemyUserDatabase`` из
``fastapi_users_db_sqlalchemy``, чтобы переход на PostgreSQL не менял
наблюдаемый контракт.
"""

import uuid
from dataclasses import replace
from typing import Any

from fastapi_users.db import BaseUserDatabase

from app.auth.user_protocol import AppUserProtocol
from app.business.domain.entities import User
from app.business.domain.errors import UserAlreadyExistsError, UserNotFoundError
from app.repositories.memory_store import InMemoryUserStore


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
