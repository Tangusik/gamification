"""Тесты сценария регистрации, входа и работы с собственным профилем."""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from app.api.deps import get_memberships_client
from app.business.domain.entities import User
from app.business.domain.errors import MembershipCheckUnavailableError

EMAIL = "student@example.com"
PASSWORD = "correct-horse-battery-staple"

Register = Callable[..., Awaitable[Response]]
Login = Callable[..., Awaitable[Response]]
AuthHeaders = Callable[..., Awaitable[dict[str, str]]]


class FakeMemberships:
    """Двойник gamification-клиента для тестов синхронизации имени (план
    11-user-name, этап 3). Управляется тестом через ``error``."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[tuple[uuid.UUID, str | None]] = []

    async def sync_profile_name(
        self, *, user_id: uuid.UUID, full_name: str | None
    ) -> int:
        self.calls.append((user_id, full_name))
        if self.error is not None:
            raise self.error
        return 1


@pytest.fixture
def fake_memberships(app: FastAPI) -> FakeMemberships:
    """Подменить клиент gamification фейком на время одного теста."""
    fake = FakeMemberships()
    app.dependency_overrides[get_memberships_client] = lambda: fake
    return fake


async def test_register_creates_plain_user_without_password_leak(
    register: Register,
) -> None:
    """Регистрация создаёт обычную учётку и не отдаёт хеш пароля.

    Роли в ответе нет: она принадлежит членству, а у только что
    зарегистрированного пользователя членств ноль.
    """
    response = await register(EMAIL, PASSWORD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == EMAIL
    assert "role" not in body
    assert "institution_id" not in body
    assert body["is_superuser"] is False
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_duplicate_email_rejected(register: Register) -> None:
    """Повторная регистрация того же email отклоняется с явным кодом."""
    first = await register(EMAIL, PASSWORD)
    assert first.status_code == 201, first.text

    second = await register(EMAIL, PASSWORD)

    assert second.status_code == 400
    assert second.json()["detail"] == "REGISTER_USER_ALREADY_EXISTS"


async def test_login_returns_bearer_token(register: Register, login: Login) -> None:
    """Вход верными данными выдаёт непустой bearer-токен."""
    await register(EMAIL, PASSWORD)

    response = await login(EMAIL, PASSWORD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert isinstance(body["access_token"], str)
    assert body["access_token"]


async def test_login_failures_are_indistinguishable(
    register: Register, login: Login
) -> None:
    """Неверный пароль и несуществующий email дают одинаковый отказ.

    Это защита от перебора: по ответу нельзя узнать, заведён ли аккаунт
    с таким email. Сравниваются и статус, и тело целиком.
    """
    await register(EMAIL, PASSWORD)

    wrong_password = await login(EMAIL, "definitely-not-the-password")
    unknown_email = await login("nobody@example.com", PASSWORD)

    assert wrong_password.status_code == 400
    assert wrong_password.json()["detail"] == "LOGIN_BAD_CREDENTIALS"
    assert unknown_email.status_code == wrong_password.status_code
    assert unknown_email.json() == wrong_password.json()


async def test_users_me_requires_token(client: AsyncClient) -> None:
    """Без токена профиль не отдаётся."""
    response = await client.get("/users/me")

    assert response.status_code == 401


async def test_users_me_returns_own_profile(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """С токеном профиль отдаётся с корректными id и email."""
    created = (await register(EMAIL, PASSWORD)).json()
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == created["id"]
    assert body["email"] == EMAIL
    assert "role" not in body


async def test_patch_me_cannot_escalate_role_or_superuser(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: Callable[[str], User]
) -> None:
    """PATCH /users/me не даёт назначить себе роль и флаг суперюзера.

    Поля ``role`` у пользователя больше нет, поэтому смысл проверки
    сместился: ключ ``role`` в теле обязан быть вычищен до конструктора
    сущности, иначе запрос упал бы с 500 вместо успешного ответа.
    """
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me",
        headers=headers,
        json={"role": "institution_admin", "is_superuser": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert "role" not in body
    assert body["is_superuser"] is False

    reread = await client.get("/users/me", headers=headers)
    assert "role" not in reread.json()
    assert reread.json()["is_superuser"] is False
    assert find_user(EMAIL).is_superuser is False


async def test_patch_me_sets_full_name(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """PATCH /users/me сохраняет имя и отдаёт его в ответе и в GET."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "Иван Иванов"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Иван Иванов"

    reread = await client.get("/users/me", headers=headers)
    assert reread.json()["full_name"] == "Иван Иванов"


async def test_patch_me_full_name_too_long_rejected(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """Имя длиннее 100 символов отклоняется схемой."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "a" * 101}
    )

    assert response.status_code == 422, response.text


async def test_patch_me_full_name_null_resets_it(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """``full_name: null`` сбрасывает ранее установленное имя."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)
    await client.patch("/users/me", headers=headers, json={"full_name": "Имя"})

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": None}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] is None

    reread = await client.get("/users/me", headers=headers)
    assert reread.json()["full_name"] is None


async def test_patch_me_full_name_empty_string_normalized_to_null(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """Пустая строка нормализуется в ``null``, а не хранится как есть."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch("/users/me", headers=headers, json={"full_name": ""})

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] is None


async def test_patch_me_full_name_blank_string_normalized_to_null(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """Строка из одних пробелов нормализуется в ``null``, как и пустая."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "   "}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] is None


async def test_patch_me_full_name_edge_spaces_trimmed(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """Краевые пробелы у непустого имени срезаются при сохранении."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "  Иван Иванов  "}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Иван Иванов"


async def test_patch_me_full_name_empty_string_triggers_sync_with_null(
    client: AsyncClient,
    register: Register,
    auth_headers: AuthHeaders,
    fake_memberships: FakeMemberships,
) -> None:
    """Сброс имени пустой строкой доезжает до синхронизации как ``None``.

    Нормализация ``""`` -> ``None`` не должна прятать ключ
    ``"full_name"`` из ``update_dict`` в ``on_after_update``: это явный
    сброс имени, а не отсутствие поля в теле запроса (см.
    ``app/auth/user_manager.py``).
    """
    created = (await register(EMAIL, PASSWORD)).json()
    headers = await auth_headers(EMAIL, PASSWORD)
    await client.patch("/users/me", headers=headers, json={"full_name": "Имя"})

    response = await client.patch("/users/me", headers=headers, json={"full_name": ""})

    assert response.status_code == 200, response.text
    assert fake_memberships.calls[-1] == (uuid.UUID(created["id"]), None)


async def test_patch_me_full_name_triggers_profile_name_sync(
    client: AsyncClient,
    register: Register,
    auth_headers: AuthHeaders,
    fake_memberships: FakeMemberships,
) -> None:
    """Смена ``full_name`` дёргает синхронизацию ровно один раз."""
    created = (await register(EMAIL, PASSWORD)).json()
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "Иван Иванов"}
    )

    assert response.status_code == 200, response.text
    assert fake_memberships.calls == [(uuid.UUID(created["id"]), "Иван Иванов")]


async def test_patch_me_without_full_name_does_not_trigger_sync(
    client: AsyncClient,
    register: Register,
    auth_headers: AuthHeaders,
    fake_memberships: FakeMemberships,
) -> None:
    """Смена пароля без ``full_name`` в теле синхронизацию не дёргает."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"password": "another-strong-password"}
    )

    assert response.status_code == 200, response.text
    assert fake_memberships.calls == []


async def test_patch_me_succeeds_even_if_profile_name_sync_fails(
    client: AsyncClient,
    register: Register,
    auth_headers: AuthHeaders,
    fake_memberships: FakeMemberships,
) -> None:
    """Недоступность gamification не должна блокировать ``PATCH /users/me``.

    Синхронизация best-effort (решение ведущего задачи, план
    11-user-name): имя сохраняется в users независимо от её исхода.
    """
    fake_memberships.error = MembershipCheckUnavailableError()
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", headers=headers, json={"full_name": "Иван Иванов"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Иван Иванов"

    reread = await client.get("/users/me", headers=headers)
    assert reread.json()["full_name"] == "Иван Иванов"


async def test_users_me_full_name_absent_by_default(
    client: AsyncClient, register: Register, auth_headers: AuthHeaders
) -> None:
    """Сразу после регистрации имя отсутствует (``None``) в профиле."""
    await register(EMAIL, PASSWORD)
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] is None


async def test_inactive_user_is_rejected(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: Callable[[str], User]
) -> None:
    """Деактивация учётки закрывает доступ по уже выданному токену."""
    headers = await auth_headers(EMAIL, PASSWORD)
    find_user(EMAIL).is_active = False

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401
