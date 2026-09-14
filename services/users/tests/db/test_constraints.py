"""Ограничения схемы: то, чего in-memory реализация не гарантирует.

Уникальность email в памяти держится кодом адаптера, поэтому при гонке
двух регистраций она не даёт ничего. Здесь арбитр — уникальный
функциональный индекс ``ix_users_email_lower``, и проверяется именно он.
"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.business.domain.errors import UserAlreadyExistsError
from app.repositories.models import User
from app.repositories.sql_alchemy import SqlAlchemyUserRepository

EMAIL = "unique@example.com"
EMAIL_OTHER_CASE = "Unique@EXAMPLE.com"
OTHER_EMAIL = "other@example.com"
PASSWORD = "correct-horse-battery-staple"
HASHED_PASSWORD = "hashed-secret"

Register = Callable[..., Awaitable[Response]]
AuthHeaders = Callable[..., Awaitable[dict[str, str]]]


async def _count_users(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Сколько записей пользователей лежит в базе прямо сейчас."""
    async with session_factory() as session:
        result = await session.execute(select(func.count()).select_from(User))
    return int(result.scalar_one())


async def test_registration_rejects_email_in_other_case(
    register: Register, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Тот же адрес в другом регистре вторым не регистрируется."""
    first = await register(EMAIL, PASSWORD)
    assert first.status_code == 201, first.text

    second = await register(EMAIL_OTHER_CASE, PASSWORD)

    assert second.status_code == 400
    assert second.json() == {"detail": "REGISTER_USER_ALREADY_EXISTS"}
    assert await _count_users(session_factory) == 1


async def test_unique_index_rejects_email_in_other_case(
    register: Register, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Индекс ``lower(email)`` отвергает дубль и в обход проверки в коде.

    Тест выше проходит и без индекса: менеджер сначала ищет по email, а
    поиск и так регистронезависим. Здесь запись идёт прямо в
    репозиторий, минуя эту проверку, — отказ может дать только сама
    схема. Без функционального индекса ``unique@`` и ``Unique@``
    сосуществовали бы, а ``get_by_email`` возвращал бы произвольного из
    двух.
    """
    created = await register(EMAIL, PASSWORD)
    assert created.status_code == 201, created.text

    async with session_factory() as session:
        with pytest.raises(UserAlreadyExistsError):
            await SqlAlchemyUserRepository(session).create(
                {"email": EMAIL_OTHER_CASE, "hashed_password": HASHED_PASSWORD}
            )

    assert await _count_users(session_factory) == 1


async def test_concurrent_registration_creates_single_user(
    register: Register, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    """Две одновременные регистрации одного email дают одну запись.

    Проверка «нет ли такого email» и вставка не атомарны, поэтому оба
    запроса могут пройти проверку. Единственный арбитр — уникальный
    индекс; от адаптера требуется перевести его нарушение в код ошибки,
    а не отдать 500 с оборванной транзакцией.
    """
    first, second = await asyncio.gather(
        register(EMAIL, PASSWORD), register(EMAIL, PASSWORD)
    )

    statuses = sorted([first.status_code, second.status_code])
    assert statuses[0] == 201, (first.text, second.text)
    # 400 — проигравший успел увидеть чужую запись проверкой в коде,
    # 409 — не успел и получил отказ уже от индекса. Оба ответа
    # законны; недопустима только пятисотка.
    assert statuses[1] in {400, 409}, (first.text, second.text)
    assert await _count_users(session_factory) == 1


async def test_patch_me_to_taken_email_leaves_database_unchanged(
    client: AsyncClient,
    register: Register,
    auth_headers: AuthHeaders,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Смена email на занятый отклоняется, и в базе ничего не меняется.

    Важна вторая половина: отказ, при котором запись всё же поехала,
    выглядел бы в ответе так же.
    """
    headers = await auth_headers(EMAIL, PASSWORD)
    taken = await register(OTHER_EMAIL, PASSWORD)
    assert taken.status_code == 201, taken.text

    response = await client.patch(
        "/users/me", json={"email": OTHER_EMAIL}, headers=headers
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "UPDATE_USER_EMAIL_ALREADY_EXISTS"}
    async with session_factory() as session:
        emails = await session.execute(select(User.email))
    assert sorted(emails.scalars().all()) == sorted([EMAIL, OTHER_EMAIL])
