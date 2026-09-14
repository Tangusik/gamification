"""Контрактные тесты хранилища пользователей.

Тесты написаны против псевдонима ``UserRepository`` и работают только
через фикстуру ``user_db``: ни конкретный класс, ни его внутреннее
состояние (``_store``) здесь не упоминаются. Благодаря этому файл
переносится на адаптер PostgreSQL без изменений — достаточно добавить
вариант в параметризацию фикстуры.
"""

import uuid
from datetime import datetime

import pytest

from app.business.domain.errors import UserAlreadyExistsError
from app.repositories.protocols import UserRepository

EMAIL = "user@example.com"
EMAIL_OTHER_CASE = "USER@Example.COM"
HASHED_PASSWORD = "hashed-secret"


async def _create_user(user_db: UserRepository, email: str = EMAIL):
    """Создать пользователя с минимальным набором обязательных полей."""
    return await user_db.create({"email": email, "hashed_password": HASHED_PASSWORD})


async def test_create_fills_domain_defaults(user_db: UserRepository) -> None:
    """create заполняет id и доменные значения по умолчанию.

    Контракт гарантирует: новый пользователь активен, не верифицирован
    и не суперпользователь, с проставленным временем создания. Роли у
    него нет вовсе — она принадлежит членству, а членств у только что
    созданного пользователя ноль.
    """
    user = await _create_user(user_db)

    assert isinstance(user.id, uuid.UUID)
    assert user.email == EMAIL
    assert user.hashed_password == HASHED_PASSWORD
    assert user.is_active is True
    assert user.is_verified is False
    assert user.is_superuser is False
    assert isinstance(user.created_at, datetime)


async def test_get_returns_created_user(user_db: UserRepository) -> None:
    """get по идентификатору возвращает ранее созданного пользователя."""
    created = await _create_user(user_db)

    found = await user_db.get(created.id)

    assert found is not None
    assert found.id == created.id
    assert found.email == created.email
    assert found.is_active == created.is_active


async def test_get_missing_id_returns_none(user_db: UserRepository) -> None:
    """Отсутствие пользователя — это None, а не исключение.

    Решение «404 или нет» принимает вышележащий слой; хранилище лишь
    сообщает об отсутствии записи.
    """
    assert await user_db.get(uuid.uuid4()) is None


async def test_get_by_email_is_case_insensitive(user_db: UserRepository) -> None:
    """Поиск по email не зависит от регистра.

    Так же ведёт себя уникальный индекс по lower(email) в БД, поэтому
    регистр ввода пользователя не влияет на результат.
    """
    created = await _create_user(user_db, EMAIL)

    found_same_case = await user_db.get_by_email(EMAIL)
    found_other_case = await user_db.get_by_email(EMAIL_OTHER_CASE)

    assert found_same_case is not None
    assert found_other_case is not None
    assert found_same_case.id == created.id
    assert found_other_case.id == created.id


async def test_get_by_email_missing_returns_none(user_db: UserRepository) -> None:
    """Поиск по незарегистрированному email возвращает None."""
    assert await user_db.get_by_email("nobody@example.com") is None


async def test_update_persists_changed_fields(user_db: UserRepository) -> None:
    """Изменения из update видны при последующем чтении.

    Проверяется именно сохранение в хранилище, а не только содержимое
    возвращённого объекта.
    """
    created = await _create_user(user_db)

    updated = await user_db.update(created, {"is_active": False, "is_verified": True})

    assert updated.is_active is False
    assert updated.is_verified is True

    reloaded = await user_db.get(created.id)
    assert reloaded is not None
    assert reloaded.is_active is False
    assert reloaded.is_verified is True


async def test_update_email_rebuilds_lookup(user_db: UserRepository) -> None:
    """После смены email находится только новый адрес.

    Типичное место бага: индекс по email обязан перестраиваться, иначе
    старый адрес продолжает резолвиться и блокирует повторную
    регистрацию.
    """
    created = await _create_user(user_db)
    new_email = "renamed@example.com"

    await user_db.update(created, {"email": new_email})

    found = await user_db.get_by_email(new_email)
    assert found is not None
    assert found.id == created.id
    assert await user_db.get_by_email(EMAIL) is None


async def test_delete_removes_user_from_both_lookups(
    user_db: UserRepository,
) -> None:
    """Удаление убирает пользователя и из выборки по id, и по email."""
    created = await _create_user(user_db)

    await user_db.delete(created)

    assert await user_db.get(created.id) is None
    assert await user_db.get_by_email(EMAIL) is None


async def test_create_duplicate_email_raises(user_db: UserRepository) -> None:
    """Повторная регистрация того же email отклоняется.

    Уникальность проверяется без учёта регистра — как и уникальный
    индекс по lower(email).
    """
    await _create_user(user_db, EMAIL)

    with pytest.raises(UserAlreadyExistsError):
        await _create_user(user_db, EMAIL)

    with pytest.raises(UserAlreadyExistsError):
        await _create_user(user_db, EMAIL_OTHER_CASE)


async def test_read_returns_detached_copy(user_db: UserRepository) -> None:
    """Прочитанный объект не является ссылкой на хранимую запись.

    Мутация полученного объекта мимо update не должна менять хранилище:
    адаптер PostgreSQL вернёт объект сессии, и без этого правила тесты
    незаметно начнут зависеть от алиасинга.
    """
    created = await _create_user(user_db)

    fetched = await user_db.get(created.id)
    assert fetched is not None
    fetched.is_active = False
    fetched.is_verified = True

    reloaded = await user_db.get(created.id)
    assert reloaded is not None
    assert reloaded.is_active is True
    assert reloaded.is_verified is False

    by_email = await user_db.get_by_email(EMAIL)
    assert by_email is not None
    by_email.email = "hijacked@example.com"

    assert await user_db.get_by_email(EMAIL) is not None
    assert await user_db.get_by_email("hijacked@example.com") is None
