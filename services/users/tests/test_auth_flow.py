"""Тесты сценария регистрации, входа и работы с собственным профилем."""

from collections.abc import Awaitable, Callable

from httpx import AsyncClient, Response

from app.business.domain.entities import User

EMAIL = "student@example.com"
PASSWORD = "correct-horse-battery-staple"

Register = Callable[..., Awaitable[Response]]
Login = Callable[..., Awaitable[Response]]
AuthHeaders = Callable[..., Awaitable[dict[str, str]]]


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


async def test_inactive_user_is_rejected(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: Callable[[str], User]
) -> None:
    """Деактивация учётки закрывает доступ по уже выданному токену."""
    headers = await auth_headers(EMAIL, PASSWORD)
    find_user(EMAIL).is_active = False

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401
