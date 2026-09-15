"""Тесты внутреннего выпуска токена в контексте учреждения.

Единственный клиент этого эндпоинта — gamification (см.
``.claude/plans/03-gamification-service.md``, раздел 4). Users проверяет
сам: служебный секрет вызывающего, подпись/срок/отзыв ``subject_token``,
активность пользователя, остаток срока. На веру принимается только пара
«учреждение + роль» — это ответственность gamification.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable

import jwt
import pytest
from fastapi_users.jwt import generate_jwt
from httpx import AsyncClient, Response

from app.business.domain.internal_errors import (
    InternalApiError,
    PasswordRejectedError,
    ServiceAuthFailedError,
    SubjectTokenRejectedError,
    UserAlreadyExistsError,
)
from app.core.config import InsecureSettingError, Settings, get_settings
from app.core.exceptions import internal_error_status

URL = "/internal/tokens/institution-context"

# Ожидаемый словарь целиком — своё пространство кодов, отдельное от
# ``access_errors`` (тот уехал в gamification вместе с членствами).
# ``UserAlreadyExistsError`` и ``PasswordRejectedError`` относятся к
# ``POST /internal/users`` (см. ``tests/test_internal_users.py``), но
# словарь один на всё пространство ``InternalApiError`` — тест полноты
# обязан видеть все объявленные коды сразу.
EXPECTED_CATALOGUE = {
    ServiceAuthFailedError: ("SERVICE_AUTH_FAILED", 401),
    SubjectTokenRejectedError: ("SUBJECT_TOKEN_REJECTED", 403),
    UserAlreadyExistsError: ("USER_ALREADY_EXISTS", 409),
    PasswordRejectedError: ("PASSWORD_REJECTED", 400),
}


def _all_internal_errors() -> set[type[InternalApiError]]:
    """Собрать все объявленные ошибки внутреннего API по дереву наследования."""
    found: set[type[InternalApiError]] = set()
    queue = [InternalApiError]
    while queue:
        for subclass in queue.pop().__subclasses__():
            found.add(subclass)
            queue.append(subclass)
    return found


def test_internal_error_catalogue_is_complete() -> None:
    """Все объявленные ошибки внутреннего API перечислены в словаре."""
    assert _all_internal_errors() == set(EXPECTED_CATALOGUE)


@pytest.mark.parametrize(("error_class", "expected"), EXPECTED_CATALOGUE.items())
def test_internal_error_codes_and_statuses(
    error_class: type[InternalApiError], expected: tuple[str, int]
) -> None:
    """Код и статус каждой ошибки закреплены и не меняются молча."""
    code, status = expected

    assert error_class.code == code
    assert internal_error_status(error_class) == status


AUDIENCE = ["fastapi-users:auth"]
ALGORITHM = "RS256"

EMAIL = "internal-tokens@example.com"
PASSWORD = "correct-horse-battery-staple"

# Секреты только для тестов; длина — единственное, что важно для
# валидации настроек (>= MIN_SERVICE_SECRET_LENGTH).
SECRET = "a" * 40
PREVIOUS_SECRET = "b" * 40

Register = Callable[..., Awaitable[Response]]
Login = Callable[..., Awaitable[Response]]
GetToken = Callable[..., Awaitable[str]]


@pytest.fixture
def internal_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    """Задать основной служебный секрет на время одного теста."""
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET", SECRET)
    get_settings.cache_clear()
    return SECRET


@pytest.fixture
def internal_secret_with_previous(
    internal_secret: str, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Задать текущий и предыдущий секрет — сценарий ротации."""
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS", PREVIOUS_SECRET)
    get_settings.cache_clear()
    return SECRET, PREVIOUS_SECRET


def _headers(secret: str) -> dict[str, str]:
    return {"X-Service-Secret": secret}


def _body(
    subject_token: str,
    institution_id: uuid.UUID | None = None,
    role: str = "teacher",
) -> dict[str, str]:
    return {
        "subject_token": subject_token,
        "institution_id": str(institution_id or uuid.uuid4()),
        "role": role,
    }


def _verifying_key() -> str:
    return get_settings().jwt_public_key.get_secret_value()


def _signing_key() -> str:
    return get_settings().jwt_private_key.get_secret_value()


def _decode(token: str) -> dict[str, object]:
    return jwt.decode(
        token, _verifying_key(), audience=AUDIENCE, algorithms=[ALGORITHM]
    )


# --- служебный секрет ------------------------------------------------


async def test_missing_secret_is_rejected(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Без заголовка секрета — SERVICE_AUTH_FAILED, а не 500 и не 403."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(URL, json=_body(token))

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


async def test_wrong_secret_is_rejected(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Неверный секрет отвергается так же, как отсутствующий."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(
        URL, json=_body(token), headers=_headers("not-the-secret")
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


async def test_empty_configured_secret_never_matches(
    client: AsyncClient, get_token: GetToken
) -> None:
    """Пустой секрет (умолчание в test) не совпадает даже с пустым заголовком.

    В local/test пустой секрет допустим для старта, но тогда любой
    внутренний вызов обязан быть отвергнут.
    """
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(URL, json=_body(token), headers=_headers(""))

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


async def test_correct_secret_issues_token(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Верный секрет и валидный subject-токен выпускают новый токен."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"access_token", "token_type"}
    assert body["token_type"] == "bearer"


async def test_previous_secret_is_accepted(
    client: AsyncClient,
    internal_secret_with_previous: tuple[str, str],
    get_token: GetToken,
) -> None:
    """Предыдущий секрет тоже принимается — на время ротации (C1)."""
    _current, previous = internal_secret_with_previous
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(URL, json=_body(token), headers=_headers(previous))

    assert response.status_code == 200, response.text


# --- subject_token -----------------------------------------------------


async def test_revoked_subject_token_is_rejected(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Отозванный (после logout) subject-токен не даёт выпустить новый."""
    token = await get_token(EMAIL, PASSWORD)
    logout = await client.post(
        "/users/auth/jwt/logout",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Requested-With": "gamification-web",
        },
    )
    assert logout.status_code == 204, logout.text

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "SUBJECT_TOKEN_REJECTED"}


async def test_expired_subject_token_is_rejected(
    client: AsyncClient,
    internal_secret: str,
    register: Register,
    find_user: Callable[[str], object],
) -> None:
    """Просроченный subject-токен отвергается."""
    await register(EMAIL, PASSWORD)
    user = find_user(EMAIL)
    token = generate_jwt(
        {"sub": str(user.id), "aud": AUDIENCE, "jti": str(uuid.uuid4())},
        _signing_key(),
        lifetime_seconds=-10,
        algorithm=ALGORITHM,
    )

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "SUBJECT_TOKEN_REJECTED"}


async def test_foreign_signed_subject_token_is_rejected(
    client: AsyncClient,
    internal_secret: str,
    register: Register,
    find_user: Callable[[str], object],
    foreign_keypair: tuple[str, str],
) -> None:
    """Токен с валидной нагрузкой, но чужой подписью, не принимается."""
    await register(EMAIL, PASSWORD)
    user = find_user(EMAIL)
    token = generate_jwt(
        {"sub": str(user.id), "aud": AUDIENCE, "jti": str(uuid.uuid4())},
        foreign_keypair[0],
        900,
        algorithm=ALGORITHM,
    )

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "SUBJECT_TOKEN_REJECTED"}


async def test_inactive_user_is_rejected(
    client: AsyncClient,
    internal_secret: str,
    get_token: GetToken,
    find_user: Callable[[str], object],
) -> None:
    """Токен деактивированного пользователя отвергается."""
    token = await get_token(EMAIL, PASSWORD)
    find_user(EMAIL).is_active = False

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "SUBJECT_TOKEN_REJECTED"}


async def test_unknown_user_is_rejected(
    client: AsyncClient, internal_secret: str
) -> None:
    """Токен нашей подписи с чужим ``sub`` тоже отвергается."""
    token = generate_jwt(
        {"sub": str(uuid.uuid4()), "aud": AUDIENCE, "jti": str(uuid.uuid4())},
        _signing_key(),
        900,
        algorithm=ALGORITHM,
    )

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "SUBJECT_TOKEN_REJECTED"}


async def test_malformed_role_is_rejected_by_validation(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Роль не по формату — 422, а не 500 и не тихое принятие."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(
        URL,
        json=_body(token, role="Not-A-Valid-Role!"),
        headers=_headers(internal_secret),
    )

    assert response.status_code == 422


async def test_extra_field_is_rejected_by_validation(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Лишнее поле в теле — 422: расхождение контракта не проглатывается."""
    token = await get_token(EMAIL, PASSWORD)
    payload = _body(token)
    payload["extra"] = "unexpected"

    response = await client.post(URL, json=payload, headers=_headers(internal_secret))

    assert response.status_code == 422


# --- форма и срок выпущенного токена ------------------------------------


async def test_issued_token_exp_not_after_presented(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """``exp`` нового токена не позже ``exp`` предъявленного."""
    token = await get_token(EMAIL, PASSWORD)
    presented_exp = _decode(token)["exp"]
    assert isinstance(presented_exp, int)

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 200, response.text
    issued_exp = _decode(response.json()["access_token"])["exp"]
    assert isinstance(issued_exp, int)
    assert issued_exp <= presented_exp


async def test_issued_token_carries_role_and_institution(
    client: AsyncClient,
    internal_secret: str,
    get_token: GetToken,
    find_user: Callable[[str], object],
) -> None:
    """Выпущенный токен несёт ``sub``, ``role`` и ``institution_id``."""
    token = await get_token(EMAIL, PASSWORD)
    user = find_user(EMAIL)
    institution_id = uuid.uuid4()

    response = await client.post(
        URL,
        json=_body(token, institution_id=institution_id, role="institution_admin"),
        headers=_headers(internal_secret),
    )

    assert response.status_code == 200, response.text
    payload = _decode(response.json()["access_token"])
    assert payload["sub"] == str(user.id)
    assert payload["role"] == "institution_admin"
    assert payload["institution_id"] == str(institution_id)
    assert isinstance(payload["exp"], int)
    assert uuid.UUID(payload["jti"])


async def test_response_has_no_store_header(
    client: AsyncClient, internal_secret: str, get_token: GetToken
) -> None:
    """Ответ с токеном никогда не должен кешироваться."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.post(
        URL, json=_body(token), headers=_headers(internal_secret)
    )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"


async def test_endpoint_is_absent_from_openapi_schema(client: AsyncClient) -> None:
    """Внутренний эндпоинт не публикуется в схеме — ``include_in_schema=False``."""
    schema = (await client.get("/openapi.json")).json()

    assert URL not in schema["paths"]


# --- логи: токен и секрет никогда не пишутся ----------------------------


async def test_token_and_secret_are_never_logged(
    client: AsyncClient,
    internal_secret: str,
    get_token: GetToken,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ни предъявленный, ни секрет, ни выпущенный токен не попадают в лог."""
    token = await get_token(EMAIL, PASSWORD)

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            URL, json=_body(token), headers=_headers(internal_secret)
        )

    assert response.status_code == 200, response.text
    issued = response.json()["access_token"]
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert token not in log_text
    assert issued not in log_text
    assert internal_secret not in log_text


async def test_audit_log_contains_expected_fields(
    client: AsyncClient,
    internal_secret: str,
    get_token: GetToken,
    find_user: Callable[[str], object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Аудит-лог содержит вызывающего, ``sub``, учреждение, роль и ``jti``."""
    token = await get_token(EMAIL, PASSWORD)
    user = find_user(EMAIL)
    institution_id = uuid.uuid4()

    with caplog.at_level(logging.INFO, logger="app.api.internal.internal_router"):
        response = await client.post(
            URL,
            json=_body(token, institution_id=institution_id, role="teacher"),
            headers=_headers(internal_secret),
        )

    assert response.status_code == 200, response.text
    new_jti = _decode(response.json()["access_token"])["jti"]
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        "gamification" in message
        and str(user.id) in message
        and str(institution_id) in message
        and "teacher" in message
        and str(new_jti) in message
        for message in messages
    )


# --- настройки: длина секрета --------------------------------------------


def test_settings_reject_short_internal_secret_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Короткий или пустой служебный секрет вне local/test роняет старт."""
    monkeypatch.setenv("USERS_ENVIRONMENT", "prod")
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("USERS_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/users")
    monkeypatch.setenv("USERS_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET", "too-short")

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


def test_settings_reject_short_previous_secret_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """То же самое для ``_PREVIOUS``, если он вообще задан."""
    monkeypatch.setenv("USERS_ENVIRONMENT", "prod")
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "postgres")
    monkeypatch.setenv("USERS_DATABASE_URL", "postgresql+asyncpg://u:p@db:5432/users")
    monkeypatch.setenv("USERS_REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET", SECRET)
    monkeypatch.setenv("USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS", "too-short")

    with pytest.raises(InsecureSettingError):
        Settings(_env_file=None)


def test_settings_allow_empty_internal_secret_in_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В local/test пустой секрет допустим — старт не падает."""
    monkeypatch.delenv("USERS_INTERNAL_GAMIFICATION_SECRET", raising=False)

    settings = Settings(_env_file=None)

    assert settings.internal_gamification_secret.get_secret_value() == ""
