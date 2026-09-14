"""Тесты проверки токена (раздел 3): критерий готовности этапа 1.

Каждый защищённый эндпоинт отвечает 401 одинаково, независимо от
причины отказа — поэтому все тесты бьют по ``GET /institutions``, самому
дешёвому защищённому маршруту.

Токены подписываются через фикстуру ``token_factory``, а не прямым
импортом хелпера из ``tests.conftest``: тот же модуль, импортированный
и через ``conftest`` (авто-обнаружение фикстур pytest), и через
``tests.conftest`` (явный импорт), — это два разных объекта Python с
двумя независимо сгенерированными ключами, и токен, подписанный одним,
не проверяется другим.
"""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from httpx import AsyncClient

PROTECTED_PATH = "/institutions"
AUDIENCE = ["fastapi-users:auth"]


async def test_valid_token_is_accepted(client: AsyncClient, token_factory) -> None:
    token = token_factory()

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200


async def test_matches_expected_audience(client: AsyncClient, token_factory) -> None:
    """Токен, подписанный именно ``fastapi-users:auth``, принимается (риск 8)."""
    token = token_factory(audience=["fastapi-users:auth"])

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200


async def test_missing_token_is_rejected(client: AsyncClient) -> None:
    response = await client.get(PROTECTED_PATH)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}
    assert response.headers["WWW-Authenticate"] == "Bearer"


async def test_foreign_key_is_rejected(
    client: AsyncClient, token_factory, foreign_keypair: tuple[str, str]
) -> None:
    """Токен, подписанный чужим ключом, отвергается."""
    private_key, _ = foreign_keypair
    token = token_factory(private_key=private_key)

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_token_without_exp_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    token = token_factory(include_exp=False)

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_expired_token_is_rejected(client: AsyncClient, token_factory) -> None:
    token = token_factory(expires_delta=timedelta(seconds=-1))

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_foreign_audience_is_rejected(client: AsyncClient, token_factory) -> None:
    token = token_factory(audience=["some-other:audience"])

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_wrong_algorithm_is_rejected(client: AsyncClient) -> None:
    """``alg: HS256`` не проходит: алгоритм задаётся настройками, а не токеном."""
    payload = {
        "sub": str(uuid.uuid4()),
        "aud": AUDIENCE,
        "exp": datetime.now(UTC) + timedelta(minutes=15),
        "jti": "11111111-2222-4333-8444-555555555555",
    }
    token = jwt.encode(
        payload, "a-sufficiently-long-hmac-secret-value", algorithm="HS256"
    )

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


async def test_malformed_authorization_header_is_rejected(client: AsyncClient) -> None:
    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": "not-a-bearer-token"}
    )

    assert response.status_code == 401


async def test_revoked_token_is_rejected(
    client: AsyncClient, app, token_factory
) -> None:
    """Отзыв (K1): denylist users отклоняет ``jti``, даже если он ещё не истёк."""

    class AlwaysRevoked:
        async def is_revoked(self, token_id: str) -> bool:
            return True

        async def ping(self) -> bool:
            return True

        async def close(self) -> None:
            return None

    app.state.token_denylist_reader = AlwaysRevoked()
    token = token_factory(token_id="11111111-2222-4333-8444-555555555555")

    response = await client.get(
        PROTECTED_PATH, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401
