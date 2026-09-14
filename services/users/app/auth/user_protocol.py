"""Контракт пользователя, завязанный на библиотеку fastapi-users.

Вынесен из доменного слоя (``app.business.domain.entities``) отдельно:
слой ``business`` не имеет права импортировать каркасы, а
``AppUserProtocol`` параметризует дженерики fastapi-users и поэтому
зависит от ``fastapi_users.models.UserProtocol``. Это осознанное
решение, а не утечка фреймворка в домен.
"""

import uuid
from datetime import datetime
from typing import Protocol

from fastapi_users.models import UserProtocol

from app.business.domain.entities import User


class AppUserProtocol(UserProtocol[uuid.UUID], Protocol):
    """Контракт пользователя сервиса: библиотечные поля плюс прикладные.

    Этим протоколом параметризуются все дженерики fastapi-users
    (``BaseUserManager[AppUserProtocol, uuid.UUID]``,
    ``FastAPIUsers[AppUserProtocol, uuid.UUID]``), поэтому и текущий
    in-memory dataclass ``User``, и будущая SQLAlchemy-модель
    удовлетворяют одному и тому же типу.

    ``is_superuser`` приходит из библиотечного протокола и остаётся
    техническим флагом владельца инсталляции — это **не роль**.
    """

    created_at: datetime
    must_change_password: bool


# Статическая проверка: in-memory сущность обязана удовлетворять
# протоколу, которым типизирован весь прикладной код.
_USER_IMPLEMENTS_PROTOCOL: type[AppUserProtocol] = User
