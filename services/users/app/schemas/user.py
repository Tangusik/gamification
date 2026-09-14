"""Pydantic-схемы пользователя поверх схем fastapi-users."""

import uuid
from datetime import datetime
from typing import Any

from fastapi_users import schemas

# Ключи, которых нет ни в схемах, ни в сущности пользователя, но которые
# клиент может прислать в теле запроса. Вычищаются до конструктора
# сущности: раньше это защищало от эскалации роли, теперь — от 500.
# ``must_change_password`` — исключение: поле есть и в схеме, и в
# сущности, но клиент не должен иметь возможность снять флаг сам через
# ``PATCH /users/me``, поэтому оно тоже вычищается здесь. Снимается флаг
# только сервером — при смене пароля (``app/auth/user_manager.py``).
# Сокращать набор нельзя, см. ``_strip_protected_fields``.
_PROTECTED_FIELDS = ("role", "institution_id", "created_at", "must_change_password")


def _strip_protected_fields(payload: dict[str, Any]) -> dict[str, Any]:
    """Удалить из полезной нагрузки поля, управляемые только сервером.

    После переезда роли в членство смысл вычищения изменился: эскалацию
    роли оно больше не предотвращает (роли у пользователя нет), но
    ``role`` из тела запроса дошёл бы до конструктора сущности, у
    которой такого поля нет, и запрос упал бы с ``TypeError``, то есть
    500 вместо успешной регистрации.
    """
    for name in _PROTECTED_FIELDS:
        payload.pop(name, None)
    return payload


class UserRead(schemas.BaseUser[uuid.UUID]):
    """Представление пользователя наружу.

    ``hashed_password`` в схеме отсутствует и не может быть отдан клиентом
    даже случайно. ``from_attributes=True`` наследуется от базовой схемы,
    поэтому объект валидируется прямо из доменного dataclass.

    Полей ``role`` и ``institution_id`` здесь нет: роль принадлежит
    членству, а членств у пользователя может быть несколько. Их отдаёт
    отдельное представление членств, а не профиль.

    ``must_change_password`` присутствует и отдаётся всегда: по нему
    клиент решает, уводить ли пользователя на смену пароля (решение C1).
    Снять флаг через тело запроса нельзя — см. ``_PROTECTED_FIELDS``.
    """

    created_at: datetime
    must_change_password: bool


class UserCreate(schemas.BaseUserCreate):
    """Тело запроса регистрации.

    Поля ``role`` и ``institution_id`` намеренно не объявлены: pydantic
    по умолчанию игнорирует лишние ключи, поэтому ``{"role": "..."}``
    в теле запроса в модель не попадёт. Самостоятельная регистрация не
    создаёт членства вовсе, поэтому доступа ни к одному учреждению она
    не даёт.
    """

    def create_update_dict(self) -> dict[str, Any]:
        """Вернуть данные для создания пользователя без серверных полей.

        Роутер fastapi-users передаёт результат этого метода прямо в
        конструктор пользователя, а полей ``role`` и ``institution_id``
        у сущности нет: без вычищения запрос с такими ключами дал бы
        500. Держится и при появлении полей в схеме.
        """
        return _strip_protected_fields(super().create_update_dict())

    def create_update_dict_superuser(self) -> dict[str, Any]:
        """Вернуть данные для пути ``safe=False`` без серверных полей.

        Встроенный суперюзерский путь fastapi-users тоже проходит через
        вычищение: роль выдаётся созданием членства в будущем
        админ-роутере, а не ``safe=False`` у стандартных схем.
        """
        return _strip_protected_fields(super().create_update_dict_superuser())


class UserUpdate(schemas.BaseUserUpdate):
    """Тело запроса обновления собственного профиля.

    Поля ``role`` нет вовсе: роль живёт в членстве, и меняет её будущий
    админ-роутер учреждения, а не владелец профиля.
    """

    def create_update_dict(self) -> dict[str, Any]:
        """Вернуть данные для обновления пользователя без серверных полей.

        Даже если поле появится в схеме, через ``PATCH /users/me`` его
        изменить нельзя — а ``role`` из тела запроса не дойдёт до
        конструктора сущности и не уронит запрос.
        """
        return _strip_protected_fields(super().create_update_dict())

    def create_update_dict_superuser(self) -> dict[str, Any]:
        """Вернуть данные для пути ``safe=False`` без серверных полей.

        Встроенный суперюзерский путь fastapi-users тоже проходит через
        вычищение: роль выдаётся созданием членства в будущем
        админ-роутере, а не ``safe=False`` у стандартных схем.
        """
        return _strip_protected_fields(super().create_update_dict_superuser())
