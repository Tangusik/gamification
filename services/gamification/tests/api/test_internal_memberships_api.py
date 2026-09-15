"""API-тесты внутреннего эндпоинта ``POST /internal/memberships/resolve``.

План `.claude/plans/10-refresh.md`, Ч2: эндпоинт зовёт только users при
refresh, аутентификация — служебный секрет ``X-Service-Secret``, а не
пользовательский токен (тело запроса вообще не содержит токена).
"""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.core.config import get_settings

SECRET = "test-internal-users-secret-" + "z" * 20
PREVIOUS_SECRET = "test-internal-users-secret-old-" + "y" * 20


def _use_secret(
    monkeypatch, *, current: str = SECRET, previous: str | None = None
) -> None:
    monkeypatch.setenv("GAMIFICATION_INTERNAL_USERS_SECRET", current)
    if previous is not None:
        monkeypatch.setenv("GAMIFICATION_INTERNAL_USERS_SECRET_PREVIOUS", previous)
    get_settings.cache_clear()


async def _create_institution(
    client: AsyncClient, token_factory
) -> tuple[str, uuid.UUID]:
    admin_id = uuid.uuid4()
    response = await client.post(
        "/institutions",
        json={"name": "Школа №1", "kind": "school"},
        headers={"Authorization": f"Bearer {token_factory(subject=admin_id)}"},
    )
    assert response.status_code == 201
    return response.json()["id"], admin_id


async def test_resolve_returns_role_for_active_membership(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    institution_id, admin_id = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(admin_id), "institution_id": institution_id},
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"role": "institution_admin"}


async def test_resolve_returns_404_for_stranger(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    institution_id, _ = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(uuid.uuid4()), "institution_id": institution_id},
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBERSHIP_NOT_ACTIVE"}


async def test_resolve_returns_404_for_unknown_institution(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(uuid.uuid4()), "institution_id": str(uuid.uuid4())},
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBERSHIP_NOT_ACTIVE"}


async def test_resolve_returns_404_for_suspended_membership(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    created = await client.post(
        "/institutions",
        json={"name": "Школа №1", "kind": "school"},
        headers={"Authorization": f"Bearer {token_factory(subject=admin_id)}"},
    )
    institution_id = created.json()["id"]
    admin_headers = {
        "Authorization": (
            f"Bearer {token_factory(subject=admin_id, institution_id=institution_id)}"
        )
    }
    invitation = await client.post(
        f"/institutions/{institution_id}/invitations", json={}, headers=admin_headers
    )
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation.json()["token"]},
        headers={"Authorization": f"Bearer {token_factory(subject=student_id)}"},
    )
    await client.patch(
        f"/institutions/{institution_id}/students/{student_id}",
        json={"status": "suspended"},
        headers=admin_headers,
    )

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(student_id), "institution_id": institution_id},
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBERSHIP_NOT_ACTIVE"}


async def test_resolve_without_secret_is_unauthorized(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    institution_id, admin_id = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(admin_id), "institution_id": institution_id},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


async def test_resolve_with_wrong_secret_is_unauthorized(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    institution_id, admin_id = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(admin_id), "institution_id": institution_id},
        headers={"X-Service-Secret": "wrong-secret"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}


async def test_resolve_with_previous_secret_is_accepted(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch, current="a-brand-new-secret-" + "n" * 20, previous=SECRET)
    institution_id, admin_id = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(admin_id), "institution_id": institution_id},
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 200
    assert response.json() == {"role": "institution_admin"}


async def test_resolve_rejects_extra_field(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    _use_secret(monkeypatch)
    institution_id, admin_id = await _create_institution(client, token_factory)

    response = await client.post(
        "/internal/memberships/resolve",
        json={
            "user_id": str(admin_id),
            "institution_id": institution_id,
            "extra": "unexpected",
        },
        headers={"X-Service-Secret": SECRET},
    )

    assert response.status_code == 422


async def test_endpoint_is_absent_from_public_schema(client: AsyncClient) -> None:
    schema = (await client.get("/openapi-gamification.json")).json()

    assert "/internal/memberships/resolve" not in schema["paths"]


async def test_endpoint_is_unreachable_without_secret_even_with_user_token(
    client: AsyncClient, app: FastAPI, token_factory, monkeypatch
) -> None:
    """Пользовательский JWT не годится вместо служебной аутентификации
    (``.claude/knowledge/07-routing.md``): предъявление обычного access
    токена вместо секрета всё равно даёт 401.
    """
    _use_secret(monkeypatch)

    response = await client.post(
        "/internal/memberships/resolve",
        json={"user_id": str(uuid.uuid4()), "institution_id": str(uuid.uuid4())},
        headers={"Authorization": f"Bearer {token_factory()}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "SERVICE_AUTH_FAILED"}
