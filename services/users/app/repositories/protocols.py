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

Контрактов учреждений и членств здесь больше нет — они переехали вместе
с сущностями в сервис gamification.
"""

import uuid

from fastapi_users.db import BaseUserDatabase

from app.auth.user_protocol import AppUserProtocol

UserRepository = BaseUserDatabase[AppUserProtocol, uuid.UUID]
