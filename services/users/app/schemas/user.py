"""Pydantic-схемы пользователя поверх схем fastapi-users."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi_users import schemas
from pydantic import BeforeValidator, Field

# Ключи, которых нет ни в схемах, ни в сущности пользователя, но которые
# клиент может прислать в теле запроса. Вычищаются до конструктора
# сущности: раньше это защищало от эскалации роли, теперь — от 500.
# ``must_change_password`` — исключение: поле есть и в схеме, и в
# сущности, но клиент не должен иметь возможность снять флаг сам через
# ``PATCH /users/me``, поэтому оно тоже вычищается здесь. Снимается флаг
# только сервером — при смене пароля (``app/auth/user_manager.py``).
# Сокращать набор нельзя, см. ``_strip_protected_fields``.
_PROTECTED_FIELDS = ("role", "institution_id", "created_at", "must_change_password")


def _normalize_full_name(value: str | None) -> str | None:
    """Привести имя к единому виду до любых других проверок поля.

    Пустая строка и строка из одних пробелов превращаются в ``None`` —
    два вида «пустого имени» в БД не нужны (решение владельца,
    2026-10-12). У непустого имени срезаются только краевые пробелы.

    Нормализация объявлена ``BeforeValidator``, то есть выполняется до
    проверки ``max_length=100`` у поля. Порядок выбран осознанно: имя с
    краевыми пробелами, умещающееся в 100 значимых символов без них,
    не должно падать в 422 из-за пробелов, которые дальше всё равно
    срезаются. Проверка длины после нормализации считает ровно то, что
    в итоге попадёт в БД.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


# Общий тип поля имени — единственное место нормализации (решение
# владельца, 2026-10-12): используется и в ``UserUpdate`` (``PATCH
# /users/me``), и внутренним роутером (``POST /internal/users``,
# ``app/api/internal/internal_router.py``), чтобы не разводить правило
# по схемам и клиентам.
#
# ``max_length`` объявлен на строковой ветке, а не на всём
# ``str | None``: ограничение длины, навешенное на union, pydantic
# пытается применить и к ``None`` — ``len(None)`` даёт ``TypeError``, то
# есть 500 на любом запросе без имени. Проверено тестами
# ``tests/test_internal_users.py``.
_FullNameValue = Annotated[str, Field(max_length=100)]

FullName = Annotated[
    _FullNameValue | None,
    BeforeValidator(_normalize_full_name),
    Field(default=None),
]


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

    ``full_name`` — единственное поле имени человека (решение владельца,
    план 11-user-name): без разбивки на части, правит его сам
    пользователь через ``PATCH /users/me``.
    """

    created_at: datetime
    must_change_password: bool
    full_name: str | None = Field(default=None, max_length=100)


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

    ``full_name`` правит сам пользователь: поле не входит в
    ``_PROTECTED_FIELDS``. ``{"full_name": null}`` сбрасывает имя —
    осознанно допустимо (план 11-user-name). Пустая строка и строка из
    пробелов нормализуются в ``None`` тем же способом (``FullName``,
    решение владельца 2026-10-12) — явный сброс имени доезжает до
    ``on_after_update`` так же, как и ``null``: ``exclude_unset``
    отражает, что поле пришло в теле запроса, а не его итоговое
    значение.
    """

    full_name: FullName

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
