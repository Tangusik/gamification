"""API-тесты эндпоинтов учеников (Ч2в плана): коды ответов."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient


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


async def test_list_students_empty_by_default(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.get(
        f"/institutions/{institution_id}/students",
        headers=_headers(
            token_factory(subject=admin_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 200
    assert response.json() == []


async def test_list_students_with_unknown_group_is_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.get(
        f"/institutions/{institution_id}/students?group_id={uuid.uuid4()}",
        headers=_headers(
            token_factory(subject=admin_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "GROUP_NOT_FOUND"}


async def test_update_student_after_invitation(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    invitation = await client.post(
        f"/institutions/{institution_id}/invitations",
        json={},
        headers=admin_headers,
    )
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation.json()["token"]},
        headers=_headers(token_factory(subject=student_id)),
    )

    response = await client.patch(
        f"/institutions/{institution_id}/students/{student_id}",
        json={"display_name": "Ученик", "status": "suspended"},
        headers=admin_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Ученик"
    assert body["status"] == "suspended"


async def test_update_student_with_invalid_status_is_422(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))

    response = await client.patch(
        f"/institutions/{institution_id}/students/{uuid.uuid4()}",
        json={"status": "invited"},
        headers=_headers(
            token_factory(subject=admin_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 422
