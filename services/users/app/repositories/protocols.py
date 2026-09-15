"""Типовые контракты хранилищ сервиса users.

Модуль задаёт единственный шов между прикладным кодом и хранилищем.
Весь код вне пакета ``app.repositories`` и модуля ``app.api.deps``
типизируется псевдонимами отсюда и **никогда** не упоминает конкретный
класс реализации (ни in-memory, ни SQLAlchemy). Благодаря этому переход
на PostgreSQL меняет только сборку адаптеров в ``app.api.deps``, а не
сигнатуры прикладных функций.

Для пользователей ``BaseUserDatabase`` из fastapi-users уже описывает
нужный набор операций, поэтому собственный Protocol не заводится: лишний
слой абстракции только разошёлся бы с библиотечным контрактом.

Контракт refresh-сессий (план 10-refresh) не дублируется здесь: он уже
объявлен как порт бизнес-слоя в ``app.business.ports`` — бизнес-слою
запрещено импортировать ``app.repositories`` (см.
``tests/test_business_imports.py``), а не наоборот, поэтому реализации
(``app.repositories.in_memory``, ``app.repositories.sql_alchemy``)
зависят от порта, а не порт от них. ``RefreshSessionRepository``
переиспользуется отсюда через реэкспорт, чтобы у прикладного кода
(``app.api.deps``) был один узнаваемый источник псевдонимов хранилищ.

Контрактов учреждений и членств здесь больше нет — они переехали вместе
с сущностями в сервис gamification.
"""

import uuid

from fastapi_users.db import BaseUserDatabase

from app.auth.user_protocol import AppUserProtocol
from app.business.ports import RefreshSessionRepository, RotationOutcome, RotationResult

UserRepository = BaseUserDatabase[AppUserProtocol, uuid.UUID]

__all__ = [
    "RefreshSessionRepository",
    "RotationOutcome",
    "RotationResult",
    "UserRepository",
]
