"""API-тесты эндпоинтов учреждений (раздел 6): создание, список, переключение.

Токены — через фикстуру ``token_factory`` (см. комментарий в
``tests/test_auth.py`` о причине не импортировать хелпер напрямую).
"""

import uuid

from httpx import AsyncClient

from app.api.deps import get_switch_institution
from app.business.use_cases.context import TokenPair


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
    }

    renamed = await client.patch(
        f"/institutions/{institution_id}",
        json={"name": "Новое имя"},
        headers=context_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Новое имя"


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
