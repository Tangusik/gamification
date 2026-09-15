"""API-тесты эндпоинтов учреждений (раздел 6): создание, список, переключение.

Токены — через фикстуру ``token_factory`` (см. комментарий в
``tests/test_auth.py`` о причине не импортировать хелпер напрямую).
"""

import uuid

from fastapi import FastAPI
from httpx import AsyncClient

from app.api.deps import get_switch_institution, get_user_accounts
from app.business.use_cases.context import TokenPair


class FakeUserAccounts:
    """Фейк клиента users для тестов, где создание аккаунта не проверяется."""

    def __init__(self, *, user_id=None):
        self._user_id = user_id or uuid.uuid4()

    async def create_account(self, *, email: str, password: str):
        return self._user_id


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
    client: AsyncClient, institution_id: str, admin_headers: dict, token_factory
) -> str:
    student_id = uuid.uuid4()
    invitation = await client.post(
        f"/institutions/{institution_id}/invitations", json={}, headers=admin_headers
    )
    await client.post(
        "/institutions/invitations/accept",
        json={"token": invitation.json()["token"]},
        headers={"Authorization": f"Bearer {token_factory(subject=student_id)}"},
    )
    return str(student_id)


async def test_create_and_list_institution(client: AsyncClient, token_factory) -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}

    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    assert created.status_code == 201
    institution_id = created.json()["id"]

    listed = await client.get("/institutions", headers=headers)
    assert listed.status_code == 200
    body = listed.json()
    assert len(body) == 1
    assert body[0]["institution_id"] == institution_id
    assert body[0]["name"] == "Школа №1"
    assert body[0]["kind"] == "school"
    assert body[0]["role"] == "institution_admin"
    assert body[0]["status"] == "active"
    assert body[0]["currency_name"] is None


async def test_list_institutions_hides_others(
    client: AsyncClient, token_factory
) -> None:
    owner_headers = {"Authorization": f"Bearer {token_factory()}"}
    stranger_headers = {"Authorization": f"Bearer {token_factory()}"}

    await client.post(
        "/institutions",
        json={"name": "Школа №1", "kind": "school"},
        headers=owner_headers,
    )

    response = await client.get("/institutions", headers=stranger_headers)

    assert response.status_code == 200
    assert response.json() == []


async def test_switch_without_membership_is_not_a_member(
    client: AsyncClient, token_factory
) -> None:
    headers = {"Authorization": f"Bearer {token_factory()}"}

    response = await client.post(f"/institutions/{uuid.uuid4()}/token", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "NOT_A_MEMBER"}


async def test_switch_after_creation_returns_context_token(
    client: AsyncClient, app, token_factory
) -> None:
    """Сквозной сценарий: создание учреждения делает создателя членом,
    достаточным для переключения (сам выпуск токена подменён фейком —
    вызов users проверяется отдельно, через httpx.MockTransport)."""

    class FakeSwitchInstitution:
        async def execute(self, *, user_id, institution_id, subject_token) -> TokenPair:
            return TokenPair(access_token="issued-token")

    app.dependency_overrides[get_switch_institution] = lambda: FakeSwitchInstitution()
    try:
        headers = {"Authorization": f"Bearer {token_factory()}"}
        created = await client.post(
            "/institutions", json={"name": "Лагерь", "kind": "camp"}, headers=headers
        )
        institution_id = created.json()["id"]

        response = await client.post(
            f"/institutions/{institution_id}/token", headers=headers
        )

        assert response.status_code == 200
        assert response.json() == {
            "access_token": "issued-token",
            "token_type": "bearer",
        }
        assert response.headers["Cache-Control"] == "no-store"
    finally:
        app.dependency_overrides.clear()


async def test_create_institution_with_empty_name_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    headers = {"Authorization": f"Bearer {token_factory()}"}

    response = await client.post(
        "/institutions", json={"name": "", "kind": "school"}, headers=headers
    )

    assert response.status_code == 422


async def test_create_institution_with_name_over_255_chars_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    headers = {"Authorization": f"Bearer {token_factory()}"}

    response = await client.post(
        "/institutions",
        json={"name": "a" * 256, "kind": "school"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_create_institution_with_name_exactly_255_chars_is_accepted(
    client: AsyncClient, token_factory
) -> None:
    headers = {"Authorization": f"Bearer {token_factory()}"}

    response = await client.post(
        "/institutions",
        json={"name": "a" * 255, "kind": "school"},
        headers=headers,
    )

    assert response.status_code == 201


async def test_non_uuid_institution_id_is_not_found(
    client: AsyncClient, token_factory
) -> None:
    """Параметр пути объявлен через ``{institution_id:uuid}`` (раздел 6)."""
    headers = {"Authorization": f"Bearer {token_factory()}"}

    response = await client.post("/institutions/not-a-uuid/token", headers=headers)

    assert response.status_code == 404


async def test_admin_gets_and_renames_institution(
    client: AsyncClient, token_factory
) -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]
    context_token = token_factory(subject=user_id, institution_id=institution_id)
    context_headers = {"Authorization": f"Bearer {context_token}"}

    fetched = await client.get(
        f"/institutions/{institution_id}", headers=context_headers
    )
    assert fetched.status_code == 200
    assert fetched.json() == {
        "id": institution_id,
        "name": "Школа №1",
        "kind": "school",
        "created_at": fetched.json()["created_at"],
        "currency_name": None,
    }

    renamed = await client.patch(
        f"/institutions/{institution_id}",
        json={"name": "Новое имя"},
        headers=context_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Новое имя"
    assert renamed.json()["currency_name"] is None


async def test_get_institution_requires_matching_context(
    client: AsyncClient, token_factory
) -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]

    response = await client.get(f"/institutions/{institution_id}", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}


async def test_rename_institution_with_empty_name_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]
    context_token = token_factory(subject=user_id, institution_id=institution_id)
    context_headers = {"Authorization": f"Bearer {context_token}"}

    response = await client.patch(
        f"/institutions/{institution_id}", json={"name": ""}, headers=context_headers
    )

    assert response.status_code == 422


async def _create_institution_with_admin_headers(
    client: AsyncClient, token_factory
) -> tuple[str, dict]:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]
    context_token = token_factory(subject=user_id, institution_id=institution_id)
    return institution_id, {"Authorization": f"Bearer {context_token}"}


async def test_set_currency_name_is_trimmed(client: AsyncClient, token_factory) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "  монетки  "},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["currency_name"] == "монетки"
    # Имя учреждения при этом не тронуто.
    assert response.json()["name"] == "Школа №1"


async def test_currency_name_not_passed_does_not_change_it(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )
    await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "монетки"},
        headers=headers,
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"name": "Новое имя"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Новое имя"
    assert response.json()["currency_name"] == "монетки"


async def test_explicit_null_clears_currency_name(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )
    await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "монетки"},
        headers=headers,
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": None},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["currency_name"] is None


async def test_currency_name_and_name_change_together(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"name": "Новое имя", "currency_name": "звёзды"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Новое имя"
    assert response.json()["currency_name"] == "звёзды"


async def test_currency_name_empty_after_trim_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "   "},
        headers=headers,
    )

    assert response.status_code == 422


async def test_currency_name_exactly_32_chars_is_accepted(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "a" * 32},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["currency_name"] == "a" * 32


async def test_currency_name_over_32_chars_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "a" * 33},
        headers=headers,
    )

    assert response.status_code == 422


async def test_currency_name_single_char_is_accepted(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "a"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["currency_name"] == "a"


async def test_teacher_and_student_cannot_change_currency_name(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=admin_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]
    admin_headers = {
        "Authorization": (
            f"Bearer {token_factory(subject=admin_id, institution_id=institution_id)}"
        )
    }
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )

    for actor_id in (uuid.UUID(teacher_id), uuid.UUID(student_id)):
        response = await client.patch(
            f"/institutions/{institution_id}",
            json={"currency_name": "монетки"},
            headers={
                "Authorization": (
                    f"Bearer "
                    f"{token_factory(subject=actor_id, institution_id=institution_id)}"
                )
            },
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "INSUFFICIENT_ROLE"}


async def test_rename_institution_with_explicit_null_name_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}", json={"name": None}, headers=headers
    )

    assert response.status_code == 422


async def test_rename_institution_requires_matching_context(
    client: AsyncClient, token_factory
) -> None:
    user_id = uuid.uuid4()
    headers = {"Authorization": f"Bearer {token_factory(subject=user_id)}"}
    created = await client.post(
        "/institutions", json={"name": "Школа №1", "kind": "school"}, headers=headers
    )
    institution_id = created.json()["id"]
    other_context_token = token_factory(subject=user_id, institution_id=uuid.uuid4())
    other_context_headers = {"Authorization": f"Bearer {other_context_token}"}

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"name": "Новое имя"},
        headers=other_context_headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}


async def test_currency_name_zero_width_space_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "​"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_currency_name_with_directional_override_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "‮абв"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_currency_name_with_control_character_is_rejected(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "a\x1bb"},
        headers=headers,
    )

    assert response.status_code == 422


async def test_currency_name_with_zwj_emoji_is_accepted(
    client: AsyncClient, token_factory
) -> None:
    institution_id, headers = await _create_institution_with_admin_headers(
        client, token_factory
    )

    response = await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "\U0001f468‍\U0001f469‍\U0001f467"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["currency_name"] == "\U0001f468‍\U0001f469‍\U0001f467"


async def test_student_sees_currency_name_in_own_institutions_list(
    client: AsyncClient, token_factory
) -> None:
    institution_id, admin_headers = await _create_institution_with_admin_headers(
        client, token_factory
    )
    await client.patch(
        f"/institutions/{institution_id}",
        json={"currency_name": "монетки"},
        headers=admin_headers,
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )

    response = await client.get(
        "/institutions",
        headers={
            "Authorization": (f"Bearer {token_factory(subject=uuid.UUID(student_id))}")
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["currency_name"] == "монетки"
