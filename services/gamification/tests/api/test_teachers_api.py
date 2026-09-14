"""API-тесты эндпоинтов преподавателей (Ч2а плана): коды ответов."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_user_accounts
from app.business.domain.errors import EmailAlreadyRegisteredError


class FakeUserAccounts:
    def __init__(self, *, user_id=None, error=None):
        self._user_id = user_id or uuid.uuid4()
        self._error = error

    async def create_account(self, *, email: str, password: str):
        if self._error is not None:
            raise self._error
        return self._user_id


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_institution(client: AsyncClient, token: str) -> str:
    response = await client.post(
        "/institutions",
        json={"name": "Школа №1", "kind": "school"},
        headers=_headers(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_admin_creates_teacher(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    app.dependency_overrides[get_user_accounts] = lambda: FakeUserAccounts()
    try:
        response = await client.post(
            f"/institutions/{institution_id}/teachers",
            json={
                "email": "teacher@example.com",
                "password": "correct horse",
                "display_name": "Иван",
            },
            headers=_headers(
                token_factory(subject=admin_id, institution_id=institution_id)
            ),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    body = response.json()
    assert body["display_name"] == "Иван"
    assert body["status"] == "active"
    assert body["group_ids"] == []


async def test_teacher_cannot_create_teacher(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    other_id = uuid.uuid4()

    response = await client.post(
        f"/institutions/{institution_id}/teachers",
        json={"email": "x@example.com", "password": "whatever123", "display_name": "X"},
        headers=_headers(
            token_factory(subject=other_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "NOT_A_MEMBER"}


async def test_create_teacher_email_already_registered(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    app.dependency_overrides[get_user_accounts] = lambda: FakeUserAccounts(
        error=EmailAlreadyRegisteredError()
    )
    try:
        response = await client.post(
            f"/institutions/{institution_id}/teachers",
            json={
                "email": "dup@example.com",
                "password": "whatever123",
                "display_name": "X",
            },
            headers=_headers(
                token_factory(subject=admin_id, institution_id=institution_id)
            ),
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert response.json() == {"detail": "EMAIL_ALREADY_REGISTERED"}


async def test_create_teacher_invalid_email_is_422(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.post(
        f"/institutions/{institution_id}/teachers",
        json={
            "email": "not-an-email",
            "password": "whatever123",
            "display_name": "X",
        },
        headers=_headers(
            token_factory(subject=admin_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 422


async def test_update_unknown_teacher_is_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.patch(
        f"/institutions/{institution_id}/teachers/{uuid.uuid4()}",
        json={"status": "suspended"},
        headers=_headers(
            token_factory(subject=admin_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_list_teachers_requires_matching_context(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.get(
        f"/institutions/{institution_id}/teachers",
        headers=_headers(token_factory(subject=admin_id)),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}
