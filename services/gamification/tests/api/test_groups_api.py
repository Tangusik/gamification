"""API-тесты эндпоинтов групп (Ч2б плана): коды ответов."""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_user_accounts


class FakeUserAccounts:
    def __init__(self, *, user_id=None):
        self._user_id = user_id or uuid.uuid4()

    async def create_account(self, *, email: str, password: str):
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


async def _create_teacher(
    client: AsyncClient, app: FastAPI, institution_id: str, admin_headers: dict
) -> str:
    teacher_user_id = uuid.uuid4()
    app.dependency_overrides[get_user_accounts] = lambda: FakeUserAccounts(
        user_id=teacher_user_id
    )
    try:
        response = await client.post(
            f"/institutions/{institution_id}/teachers",
            json={
                "email": f"{teacher_user_id}@example.com",
                "password": "correct horse",
                "display_name": "Преподаватель",
            },
            headers=admin_headers,
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 201
    return str(teacher_user_id)


async def _create_student(
    client: AsyncClient,
    institution_id: str,
    admin_headers: dict,
    token_factory,
) -> str:
    student_id = uuid.uuid4()
    invitation = await client.post(
        f"/institutions/{institution_id}/invitations", json={}, headers=admin_headers
    )
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation.json()["token"]},
        headers=_headers(token_factory(subject=student_id)),
    )
    return str(student_id)


async def test_create_and_list_groups(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))

    created = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "Группа"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["teacher_ids"] == []
    assert created.json()["students_count"] == 0

    listed = await client.get(f"/institutions/{institution_id}/groups", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_duplicate_group_name_is_conflict(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))
    await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "Группа"},
        headers=headers,
    )

    response = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "группа"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "GROUP_NAME_TAKEN"}


async def test_delete_unknown_group_is_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))

    response = await client.delete(
        f"/institutions/{institution_id}/groups/{uuid.uuid4()}", headers=headers
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "GROUP_NOT_FOUND"}


async def test_attach_unknown_teacher_is_member_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))
    group = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "Группа"},
        headers=headers,
    )
    group_id = group.json()["id"]

    response = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/teachers/{uuid.uuid4()}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_attach_and_detach_student_is_idempotent(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))
    invitation = await client.post(
        f"/institutions/{institution_id}/invitations", json={}, headers=headers
    )
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation.json()["token"]},
        headers=_headers(token_factory(subject=student_id)),
    )
    group = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "Группа"},
        headers=headers,
    )
    group_id = group.json()["id"]

    first = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/students/{student_id}",
        headers=headers,
    )
    second = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/students/{student_id}",
        headers=headers,
    )
    assert first.status_code == 204
    assert second.status_code == 204

    listed = await client.get(
        f"/institutions/{institution_id}/students?group_id={group_id}", headers=headers
    )
    assert len(listed.json()) == 1

    first_delete = await client.delete(
        f"/institutions/{institution_id}/groups/{group_id}/students/{student_id}",
        headers=headers,
    )
    second_delete = await client.delete(
        f"/institutions/{institution_id}/groups/{group_id}/students/{student_id}",
        headers=headers,
    )
    assert first_delete.status_code == 204
    assert second_delete.status_code == 204


async def test_attach_teacher_from_other_institution_is_member_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_a_id = uuid.uuid4()
    admin_b_id = uuid.uuid4()
    institution_a_id = await _create_institution(
        client, token_factory(subject=admin_a_id)
    )
    institution_b_id = await _create_institution(
        client, token_factory(subject=admin_b_id)
    )
    headers_a = _headers(
        token_factory(subject=admin_a_id, institution_id=institution_a_id)
    )
    headers_b = _headers(
        token_factory(subject=admin_b_id, institution_id=institution_b_id)
    )
    teacher_user_id = await _create_teacher(client, app, institution_b_id, headers_b)
    group = await client.post(
        f"/institutions/{institution_a_id}/groups",
        json={"name": "Группа"},
        headers=headers_a,
    )
    group_id = group.json()["id"]

    response = await client.put(
        f"/institutions/{institution_a_id}/groups/{group_id}/teachers/{teacher_user_id}",
        headers=headers_a,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_attach_student_from_other_institution_is_member_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_a_id = uuid.uuid4()
    admin_b_id = uuid.uuid4()
    institution_a_id = await _create_institution(
        client, token_factory(subject=admin_a_id)
    )
    institution_b_id = await _create_institution(
        client, token_factory(subject=admin_b_id)
    )
    headers_a = _headers(
        token_factory(subject=admin_a_id, institution_id=institution_a_id)
    )
    headers_b = _headers(
        token_factory(subject=admin_b_id, institution_id=institution_b_id)
    )
    student_id = await _create_student(
        client, institution_b_id, headers_b, token_factory
    )
    group = await client.post(
        f"/institutions/{institution_a_id}/groups",
        json={"name": "Группа"},
        headers=headers_a,
    )
    group_id = group.json()["id"]

    response = await client.put(
        f"/institutions/{institution_a_id}/groups/{group_id}/students/{student_id}",
        headers=headers_a,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_attach_student_as_group_teacher_is_member_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    headers = _headers(token_factory(subject=admin_id, institution_id=institution_id))
    student_id = await _create_student(client, institution_id, headers, token_factory)
    group = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": "Группа"},
        headers=headers,
    )
    group_id = group.json()["id"]

    response = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/teachers/{student_id}",
        headers=headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_attach_teacher_to_group_of_other_institution_is_group_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_a_id = uuid.uuid4()
    admin_b_id = uuid.uuid4()
    institution_a_id = await _create_institution(
        client, token_factory(subject=admin_a_id)
    )
    institution_b_id = await _create_institution(
        client, token_factory(subject=admin_b_id)
    )
    headers_a = _headers(
        token_factory(subject=admin_a_id, institution_id=institution_a_id)
    )
    headers_b = _headers(
        token_factory(subject=admin_b_id, institution_id=institution_b_id)
    )
    teacher_user_id = await _create_teacher(client, app, institution_b_id, headers_b)
    group = await client.post(
        f"/institutions/{institution_a_id}/groups",
        json={"name": "Группа"},
        headers=headers_a,
    )
    group_id = group.json()["id"]

    response = await client.put(
        f"/institutions/{institution_b_id}/groups/{group_id}/teachers/{teacher_user_id}",
        headers=headers_b,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "GROUP_NOT_FOUND"}
