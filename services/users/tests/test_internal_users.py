"""Тесты внутреннего заведения аккаунта с временным паролем.

Единственный клиент этого эндпоинта — gamification (решение А1,
``.claude/plans/05-admin-features.md``, Ч1). Users создаёт аккаунт тем же
путём, что и публичная регистрация (``UserManager.create(safe=True,
must_change_password=True)``), одной записью в хранилище.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient

from app.core.config import get_settings

URL = "/internal/users"

EMAIL = "internal-users@example.com"
PASSWORD = "correct-horse-battery-staple"

# Секрет только для тестов; длина — единственное, что важно для валидации
# настроек (>= MIN_SERVICE_SECRET_LENGTH, см. test_internal_tokens.py).
SECRET = "a" * 40


@pytest.fixture
def internal_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Задать служебный секрет на время одного теста."""
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET", SECRET)
    get_settings.cache_clear()
    return SECRET


def _headers(secret: str) -> dict[str, str]:
    return {"X-Service-Secret": secret}


def _body(email: str = EMAIL, password: str = PASSWORD) -> dict[str, str]:
    return {"email": email, "password": password}


# --- служебный секрет ------------------------------------------------


async def test_missing_secret_is_rejected(client: AsyncClient) -> None:
    """Без секрета — 401 SERVICE_AUTH_FAILED, аккаунт не создаётся."""
    response = await client.post(URL, json=_body())

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


# --- создание ----------------------------------------------------------


async def test_create_user_sets_must_change_password_flag(
    client: AsyncClient,
    internal_secret: str,
    find_user: Callable[[str], object],
) -> None:
    """Создание — 201, флаг временного пароля выставлен сразу."""
    response = await client.post(URL, json=_body(), headers=_headers(internal_secret))

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id"}
    assert uuid.UUID(body["id"])

    user = find_user(EMAIL)
    assert user.must_change_password is True


async def test_duplicate_email_case_insensitive_is_rejected(
    client: AsyncClient, internal_secret: str
) -> None:
    """``A@B.C`` при существующем ``a@b.c`` — тот же 409, без учёта регистра."""
    first = await client.post(
        URL, json=_body(email="a@b.c"), headers=_headers(internal_secret)
    )
    assert first.status_code == 201, first.text

    response = await client.post(
        URL, json=_body(email="A@B.C"), headers=_headers(internal_secret)
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "USER_ALREADY_EXISTS"}


async def test_short_password_is_rejected(
    client: AsyncClient, internal_secret: str
) -> None:
    """Пароль из 7 символов — 400 PASSWORD_REJECTED, аккаунт не создаётся."""
    response = await client.post(
        URL, json=_body(password="short12"), headers=_headers(internal_secret)
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "PASSWORD_REJECTED"}


async def test_extra_field_is_rejected_by_validation(
    client: AsyncClient, internal_secret: str
) -> None:
    """Лишнее поле в теле — 422: расхождение контракта не проглатывается."""
    payload = _body()
    payload["extra"] = "unexpected"

    response = await client.post(URL, json=payload, headers=_headers(internal_secret))

    assert response.status_code == 422


async def test_password_and_email_are_never_logged(
    client: AsyncClient,
    internal_secret: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ни email, ни пароль не попадают в лог, даже при отказе пароля."""
    with caplog.at_level(logging.DEBUG):
        ok = await client.post(URL, json=_body(), headers=_headers(internal_secret))
        assert ok.status_code == 201, ok.text

        rejected = await client.post(
            URL,
            json=_body(email="other@example.com", password="short12"),
            headers=_headers(internal_secret),
        )
        assert rejected.status_code == 400

    duplicate = await client.post(URL, json=_body(), headers=_headers(internal_secret))
    assert duplicate.status_code == 409

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert EMAIL not in log_text
    assert PASSWORD not in log_text
    assert "other@example.com" not in log_text
    assert "short12" not in log_text

    # ``getMessage()`` не видит то, что попало через ``exc_info`` или
    # было отформатировано отдельно (``exc_text``) — секрет мог бы
    # проскочить именно туда, а не в текст сообщения.
    formatter = logging.Formatter()
    formatted_text = "\n".join(formatter.format(record) for record in caplog.records)
    assert EMAIL not in formatted_text
    assert PASSWORD not in formatted_text
    assert "other@example.com" not in formatted_text
    assert "short12" not in formatted_text
    assert EMAIL not in caplog.text
    assert PASSWORD not in caplog.text


# --- смена пароля снимает флаг ------------------------------------------


async def test_password_change_clears_flag(
    client: AsyncClient,
    internal_secret: str,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    """Смена пароля через ``PATCH /users/me`` снимает временный флаг."""
    created = await client.post(URL, json=_body(), headers=_headers(internal_secret))
    assert created.status_code == 201, created.text

    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", json={"password": "new-correct-horse-battery"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is False


async def test_reusing_temporary_password_is_rejected(
    client: AsyncClient,
    internal_secret: str,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
    find_user: Callable[[str], object],
) -> None:
    """«Смена» пароля на тот же временный — отказ, флаг остаётся."""
    created = await client.post(URL, json=_body(), headers=_headers(internal_secret))
    assert created.status_code == 201, created.text

    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", json={"password": PASSWORD}, headers=headers
    )

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "UPDATE_USER_INVALID_PASSWORD"}
    assert find_user(EMAIL).must_change_password is True


async def test_setting_flag_field_directly_is_ignored(
    client: AsyncClient,
    internal_secret: str,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    """``PATCH /users/me`` без пароля не снимает флаг, даже если его прислать явно."""
    created = await client.post(URL, json=_body(), headers=_headers(internal_secret))
    assert created.status_code == 201, created.text

    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", json={"must_change_password": False}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is True


async def test_get_me_returns_flag(
    client: AsyncClient,
    internal_secret: str,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    """``GET /users/me`` отдаёт поле ``must_change_password``."""
    created = await client.post(URL, json=_body(), headers=_headers(internal_secret))
    assert created.status_code == 201, created.text

    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["must_change_password"] is True
