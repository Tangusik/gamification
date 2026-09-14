"""Тесты состава JWT-claims и проверки токена на защищённом эндпоинте."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import jwt
from fastapi_users.jwt import generate_jwt
from httpx import AsyncClient, Response

from app.business.domain.entities import InstitutionContext, User
from app.business.use_cases.token_claims import build_token_claims
from app.core.config import get_settings

EMAIL = "claims@example.com"
PASSWORD = "correct-horse-battery-staple"
AUDIENCE = ["fastapi-users:auth"]
ALGORITHM = "RS256"

Register = Callable[..., Awaitable[Response]]
Login = Callable[..., Awaitable[Response]]


def _bearer(token: str) -> dict[str, str]:
    """Собрать заголовок авторизации из готового токена."""
    return {"Authorization": f"Bearer {token}"}


def _payload_for(
    user_id: uuid.UUID, audience: list[str] | None = None
) -> dict[str, object]:
    """Собрать нагрузку токена, как это делает стратегия сервиса.

    Контекста учреждения нет: так выглядит токен сразу после логина.
    """
    return {
        "sub": str(user_id),
        "aud": audience if audience is not None else AUDIENCE,
        "jti": str(uuid.uuid4()),
    }


def _signing_key() -> str:
    """Приватный ключ работающего сервиса."""
    return get_settings().jwt_private_key.get_secret_value()


def _verifying_key() -> str:
    """Публичный ключ работающего сервиса."""
    return get_settings().jwt_public_key.get_secret_value()


def _user() -> User:
    """Пользователь без роли: роль принадлежит членству в gamification."""
    return User(id=uuid.uuid4(), email=EMAIL, hashed_password="hashed-secret")


def test_build_token_claims_exposes_only_routing_data() -> None:
    """В claims уходят только роль и учреждение — ничего лишнего.

    Служебные поля токена (``sub``, ``aud``, ``exp``, ``jti``) задаёт
    стратегия, а email и хеш пароля не должны попадать в читаемый всеми
    токен.
    """
    user = _user()
    context = InstitutionContext(institution_id=uuid.uuid4(), role="teacher")

    claims = build_token_claims(user, context)

    assert set(claims) == {"role", "institution_id"}
    assert claims["role"] == "teacher"
    assert claims["institution_id"] == str(context.institution_id)


def test_build_token_claims_without_context_omits_keys() -> None:
    """Без контекста ключей нет вовсе — именно отсутствие, а не ``null``.

    По отсутствию ``role`` соседние сервисы отличают владельца
    инсталляции от актора учреждения, не выдумывая отдельного значения
    роли. ``null`` эту разницу стёр бы.
    """
    claims = build_token_claims(_user(), None)

    assert claims == {}
    assert "role" not in claims
    assert "institution_id" not in claims


async def test_issued_token_payload(register: Register, login: Login) -> None:
    """Токен логина несёт sub, aud, jti и срок — но не контекст учреждения.

    Логин выдаёт токен **без контекста**: учреждение появляется только
    внутренним выпуском (``POST /internal/tokens/institution-context``).
    Проверяется именно отсутствие ключей, а не их значение ``null``.
    """
    created = (await register(EMAIL, PASSWORD)).json()
    token = (await login(EMAIL, PASSWORD)).json()["access_token"]

    payload = jwt.decode(
        token, _verifying_key(), audience=AUDIENCE, algorithms=[ALGORITHM]
    )

    assert payload["sub"] == created["id"]
    assert payload["aud"] == AUDIENCE
    assert "role" not in payload
    assert "institution_id" not in payload
    assert isinstance(payload["exp"], int)
    assert uuid.UUID(payload["jti"])
    assert "email" not in payload
    assert "hashed_password" not in payload


async def test_issued_tokens_have_distinct_jti(
    login: Login, register: Register
) -> None:
    """Каждый выпуск получает свой ``jti``.

    На нём держится отзыв: общий идентификатор на все токены
    пользователя гасил бы все сессии разом, а не одну.
    """
    await register(EMAIL, PASSWORD)
    first = (await login(EMAIL, PASSWORD)).json()["access_token"]
    second = (await login(EMAIL, PASSWORD)).json()["access_token"]

    identifiers = {
        jwt.decode(token, _verifying_key(), audience=AUDIENCE, algorithms=[ALGORITHM])[
            "jti"
        ]
        for token in (first, second)
    }

    assert len(identifiers) == 2


async def test_token_signed_with_foreign_key_rejected(
    client: AsyncClient,
    register: Register,
    find_user: Callable[[str], User],
    foreign_keypair: tuple[str, str],
) -> None:
    """Токен с валидной нагрузкой, но чужой подписью, не пускает внутрь."""
    await register(EMAIL, PASSWORD)
    token = generate_jwt(
        _payload_for(find_user(EMAIL).id), foreign_keypair[0], 900, algorithm=ALGORITHM
    )

    response = await client.get("/users/me", headers=_bearer(token))

    assert response.status_code == 401


async def test_expired_token_rejected(
    client: AsyncClient, register: Register, find_user: Callable[[str], User]
) -> None:
    """Просроченный токен не даёт доступа к профилю."""
    await register(EMAIL, PASSWORD)
    token = generate_jwt(
        _payload_for(find_user(EMAIL).id),
        _signing_key(),
        lifetime_seconds=-10,
        algorithm=ALGORITHM,
    )
    unverified = jwt.decode(token, options={"verify_signature": False})
    assert unverified["exp"] < int(datetime.now(UTC).timestamp())

    response = await client.get("/users/me", headers=_bearer(token))

    assert response.status_code == 401


async def test_token_without_expiry_rejected(
    client: AsyncClient, register: Register, find_user: Callable[[str], User]
) -> None:
    """Токен без ``exp`` не принимается, хотя подписан нашим ключом.

    Библиотечная проверка приняла бы его бессрочно: PyJWT валидирует
    срок, только если claim присутствует. Сервис требует ``exp`` явно,
    иначе бессрочный bearer жил бы вечно и при работающем denylist.
    """
    await register(EMAIL, PASSWORD)
    token = generate_jwt(
        _payload_for(find_user(EMAIL).id),
        _signing_key(),
        lifetime_seconds=None,
        algorithm=ALGORITHM,
    )
    assert "exp" not in jwt.decode(token, options={"verify_signature": False})

    response = await client.get("/users/me", headers=_bearer(token))

    assert response.status_code == 401


async def test_token_with_foreign_audience_rejected(
    client: AsyncClient, register: Register, find_user: Callable[[str], User]
) -> None:
    """Расхождение аудитории даёт молчаливый 401, а не доступ.

    Тест фиксирует поведение: если выпуск и проверка токена разойдутся
    по ``aud``, все защищённые эндпоинты начнут отвечать 401 без
    диагностики в теле ответа.
    """
    await register(EMAIL, PASSWORD)
    token = generate_jwt(
        _payload_for(find_user(EMAIL).id, ["some-other:audience"]),
        _signing_key(),
        900,
        algorithm=ALGORITHM,
    )

    response = await client.get("/users/me", headers=_bearer(token))

    assert response.status_code == 401


async def test_token_issued_with_context_carries_role_and_institution(
    register: Register,
    find_user: Callable[[str], User],
    context_token: Callable[..., Awaitable[str]],
) -> None:
    """Токен, выпущенный в контексте учреждения, несёт роль и учреждение."""
    await register(EMAIL, PASSWORD)
    user = find_user(EMAIL)
    context = InstitutionContext(institution_id=uuid.uuid4(), role="teacher")

    token = await context_token(user, context)
    payload = jwt.decode(
        token, _verifying_key(), audience=AUDIENCE, algorithms=[ALGORITHM]
    )

    assert payload["role"] == "teacher"
    assert payload["institution_id"] == str(context.institution_id)
    assert payload["sub"] == str(user.id)


async def test_bootstrap_admin_token_has_no_context(
    bootstrap_admin: tuple[str, str], login: Login
) -> None:
    """Токен владельца инсталляции приходит без ``role`` и учреждения.

    Bootstrap-админ никогда не получает контекст: логин по-прежнему
    выдаёт токен без него, а внутренний выпуск для него не вызывается.
    """
    admin_email, admin_password = bootstrap_admin

    token = (await login(admin_email, admin_password)).json()["access_token"]
    payload = jwt.decode(
        token, _verifying_key(), audience=AUDIENCE, algorithms=[ALGORITHM]
    )

    assert "role" not in payload
    assert "institution_id" not in payload
    assert payload["sub"]
