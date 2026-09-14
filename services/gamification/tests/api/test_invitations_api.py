"""API-тесты эндпоинтов приглашений (раздел 6): критерии готовности этапа 4.

Промоушен пользователя до ``teacher`` в тестах идёт напрямую через
``InMemoryStore`` за фасадом ``app.state.uow_factory()``: этот этап не
вводит API назначения роли (раздел «Что не входит» плана), приглашение
всегда выдаёт ``student``.
"""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.business.domain.enums import MembershipStatus, UserRole


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _promote_to_teacher(
    app: FastAPI, *, user_id: uuid.UUID, institution_id
) -> None:
    uow = app.state.uow_factory()
    scope = await uow.for_institution(uuid.UUID(str(institution_id)))
    membership = await scope.memberships.get_for_user(user_id)
    uow._store.memberships[membership.id].role = UserRole.TEACHER  # noqa: SLF001


async def _create_institution(client: AsyncClient, token: str) -> str:
    response = await client.post(
        "/institutions",
        json={"name": "Школа №1", "kind": "school"},
        headers=_headers(token),
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_student_cannot_create_invitation(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)

    student_id = uuid.uuid4()
    student_token = token_factory(subject=student_id)
    accept = await client.post(
        "/institutions/invitations/accept",
        json={
            "token": (
                await client.post(
                    f"/institutions/{institution_id}/invitations",
                    json={},
                    headers=_headers(
                        token_factory(subject=admin_id, institution_id=institution_id)
                    ),
                )
            ).json()["token"]
        },
        headers=_headers(student_token),
    )
    assert accept.status_code == 200

    response = await client.post(
        f"/institutions/{institution_id}/invitations",
        json={},
        headers=_headers(
            token_factory(subject=student_id, institution_id=institution_id)
        ),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "INSUFFICIENT_ROLE"}


async def test_create_invitation_requires_matching_context(
    client: AsyncClient, token_factory
) -> None:
    admin_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)

    no_context = await client.post(
        f"/institutions/{institution_id}/invitations",
        json={},
        headers=_headers(token_factory(subject=admin_id)),
    )
    wrong_context = await client.post(
        f"/institutions/{institution_id}/invitations",
        json={},
        headers=_headers(token_factory(subject=admin_id, institution_id=uuid.uuid4())),
    )

    assert no_context.status_code == 403
    assert no_context.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}
    assert wrong_context.status_code == 403
    assert wrong_context.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}


async def test_create_and_list_invitation_defaults_and_cache_control(
    client: AsyncClient, token_factory
) -> None:
    admin_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)
    context_token = token_factory(subject=admin_id, institution_id=institution_id)

    created = await client.post(
        f"/institutions/{institution_id}/invitations",
        json={},
        headers=_headers(context_token),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["max_uses"] == 1
    assert body["uses_count"] == 0
    assert body["role"] == "student"
    assert body["revoked_at"] is None
    assert body["token"]
    assert created.headers["Cache-Control"] == "no-store"

    listed = await client.get(
        f"/institutions/{institution_id}/invitations", headers=_headers(context_token)
    )
    assert listed.status_code == 200
    assert listed.headers["Cache-Control"] == "no-store"
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == body["id"]


async def test_teacher_sees_only_own_and_cannot_revoke_foreign(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)
    admin_context = token_factory(subject=admin_id, institution_id=institution_id)

    admin_invitation = (
        await client.post(
            f"/institutions/{institution_id}/invitations",
            json={},
            headers=_headers(admin_context),
        )
    ).json()

    await client.post(
        "/institutions/invitations/accept",
        json={"token": admin_invitation["token"]},
        headers=_headers(token_factory(subject=teacher_id)),
    )
    await _promote_to_teacher(app, user_id=teacher_id, institution_id=institution_id)
    teacher_context = token_factory(subject=teacher_id, institution_id=institution_id)

    teacher_invitation = (
        await client.post(
            f"/institutions/{institution_id}/invitations",
            json={},
            headers=_headers(teacher_context),
        )
    ).json()

    teacher_list = await client.get(
        f"/institutions/{institution_id}/invitations", headers=_headers(teacher_context)
    )
    assert [item["id"] for item in teacher_list.json()] == [teacher_invitation["id"]]

    admin_list = await client.get(
        f"/institutions/{institution_id}/invitations", headers=_headers(admin_context)
    )
    assert {item["id"] for item in admin_list.json()} == {
        admin_invitation["id"],
        teacher_invitation["id"],
    }

    forbidden_revoke = await client.delete(
        f"/institutions/{institution_id}/invitations/{admin_invitation['id']}",
        headers=_headers(teacher_context),
    )
    assert forbidden_revoke.status_code == 404
    assert forbidden_revoke.json() == {"detail": "INVITATION_INVALID"}

    admin_revoke = await client.delete(
        f"/institutions/{institution_id}/invitations/{admin_invitation['id']}",
        headers=_headers(admin_context),
    )
    assert admin_revoke.status_code == 204
    # Повторный отзыв уже отозванного — идемпотентно.
    admin_revoke_again = await client.delete(
        f"/institutions/{institution_id}/invitations/{admin_invitation['id']}",
        headers=_headers(admin_context),
    )
    assert admin_revoke_again.status_code == 204


async def test_invitations_are_isolated_between_institutions(
    client: AsyncClient, token_factory
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    institution_a = await _create_institution(client, token_factory(subject=admin_a))
    institution_b = await _create_institution(client, token_factory(subject=admin_b))
    context_a = token_factory(subject=admin_a, institution_id=institution_a)
    context_b = token_factory(subject=admin_b, institution_id=institution_b)

    invitation_a = (
        await client.post(
            f"/institutions/{institution_a}/invitations",
            json={},
            headers=_headers(context_a),
        )
    ).json()

    list_b = await client.get(
        f"/institutions/{institution_b}/invitations", headers=_headers(context_b)
    )
    assert list_b.json() == []

    revoke_from_b = await client.delete(
        f"/institutions/{institution_b}/invitations/{invitation_a['id']}",
        headers=_headers(context_b),
    )
    assert revoke_from_b.status_code == 404
    assert revoke_from_b.json() == {"detail": "INVITATION_INVALID"}


async def test_accept_revoked_or_unknown_token_is_invalid(
    client: AsyncClient, token_factory
) -> None:
    admin_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)
    context_token = token_factory(subject=admin_id, institution_id=institution_id)

    invitation = (
        await client.post(
            f"/institutions/{institution_id}/invitations",
            json={},
            headers=_headers(context_token),
        )
    ).json()
    await client.delete(
        f"/institutions/{institution_id}/invitations/{invitation['id']}",
        headers=_headers(context_token),
    )

    revoked_response = await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=uuid.uuid4())),
    )
    unknown_response = await client.post(
        "/institutions/invitations/accept",
        json={"token": "does-not-exist"},
        headers=_headers(token_factory(subject=uuid.uuid4())),
    )

    for response in (revoked_response, unknown_response):
        assert response.status_code == 404
        assert response.json() == {"detail": "INVITATION_INVALID"}


async def test_accept_exhausted_link_is_invalid_for_third_user(
    client: AsyncClient, token_factory
) -> None:
    admin_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)
    context_token = token_factory(subject=admin_id, institution_id=institution_id)

    invitation = (
        await client.post(
            f"/institutions/{institution_id}/invitations",
            json={"max_uses": 1},
            headers=_headers(context_token),
        )
    ).json()

    first_student = uuid.uuid4()
    accepted = await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=first_student)),
    )
    assert accepted.status_code == 200

    repeat = await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=first_student)),
    )
    assert repeat.status_code == 200
    assert repeat.json() == accepted.json()

    third_student = uuid.uuid4()
    third_response = await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=third_student)),
    )
    assert third_response.status_code == 404
    assert third_response.json() == {"detail": "INVITATION_INVALID"}


async def test_accept_by_suspended_member_is_rejected(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    admin_token = token_factory(subject=admin_id)
    institution_id = await _create_institution(client, admin_token)
    context_token = token_factory(subject=admin_id, institution_id=institution_id)

    invitation = (
        await client.post(
            f"/institutions/{institution_id}/invitations",
            json={"max_uses": 5},
            headers=_headers(context_token),
        )
    ).json()
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=student_id)),
    )

    uow = app.state.uow_factory()
    scope = await uow.for_institution(uuid.UUID(str(institution_id)))
    membership = await scope.memberships.get_for_user(student_id)
    uow._store.memberships[membership.id].status = MembershipStatus.SUSPENDED  # noqa: SLF001

    response = await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation["token"]},
        headers=_headers(token_factory(subject=student_id)),
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "MEMBERSHIP_SUSPENDED"}
