"""API-тесты эндпоинтов маркета (план 07, Ч1): статусы, 422, изоляция H1."""

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


async def _accrue(
    client: AsyncClient,
    institution_id: str,
    student_id: str,
    admin_headers: dict,
    amount: int,
) -> None:
    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": amount},
        headers=admin_headers,
    )
    assert response.status_code == 201


async def _create_privilege(
    client: AsyncClient,
    institution_id: str,
    admin_headers: dict,
    *,
    price=30,
    stock=None,
) -> str:
    payload = {"title": "Кофе", "price": price}
    if stock is not None:
        payload["stock"] = stock
    response = await client.post(
        f"/institutions/{institution_id}/privileges",
        json=payload,
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_teacher_and_student_cannot_create_privilege(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    student_headers = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
    )

    response = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "Кофе", "price": 10},
        headers=student_headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "INSUFFICIENT_ROLE"}


async def test_privileges_without_stock_field_means_unlimited(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )

    response = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "Кофе", "price": 10},
        headers=admin_headers,
    )

    assert response.status_code == 201
    assert response.json()["stock"] is None


async def test_patch_privilege_distinguishes_unset_from_null_stock(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    privilege_id = await _create_privilege(
        client, institution_id, admin_headers, price=10, stock=5
    )

    # Поле не передано — остаток не меняется.
    unchanged = await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"title": "Кофе с молоком"},
        headers=admin_headers,
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["stock"] == 5

    # Явный null — снять ограничение (У11).
    cleared = await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"stock": None},
        headers=admin_headers,
    )
    assert cleared.status_code == 200
    assert cleared.json()["stock"] is None

    # title не может быть явно обнулён.
    rejected = await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"title": None},
        headers=admin_headers,
    )
    assert rejected.status_code == 422


async def test_create_privilege_rejects_nul_and_blank_title(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    """Находка ревью: NUL в `title` давал 500 (SQLSTATE 22021), строка из
    пробелов проходила как валидная (У6 не выполнено).
    """
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )

    nul_title = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "a\x00", "price": 10},
        headers=admin_headers,
    )
    assert nul_title.status_code == 422

    blank_title = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "   ", "price": 10},
        headers=admin_headers,
    )
    assert blank_title.status_code == 422

    trimmed = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "  Кофе  ", "description": "  ", "price": 10},
        headers=admin_headers,
    )
    assert trimmed.status_code == 201
    assert trimmed.json()["title"] == "Кофе"
    # Пустое после обрезки описание — null (У6).
    assert trimmed.json()["description"] is None


async def test_create_privilege_rejects_stock_above_int32(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    """Находка ревью: `stock` за пределами `integer` давал 500 (SQLSTATE
    22003) вместо 422 — граница колонки, а не бизнес-лимит.
    """
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )

    response = await client.post(
        f"/institutions/{institution_id}/privileges",
        json={"title": "Кофе", "price": 10, "stock": 3_000_000_000},
        headers=admin_headers,
    )
    assert response.status_code == 422


async def test_patch_privilege_rejects_nul_and_blank_title(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    privilege_id = await _create_privilege(client, institution_id, admin_headers)

    nul_title = await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"title": "a\x00"},
        headers=admin_headers,
    )
    assert nul_title.status_code == 422

    blank_title = await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"title": "   "},
        headers=admin_headers,
    )
    assert blank_title.status_code == 422


async def test_patch_unknown_privilege_is_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )

    response = await client.patch(
        f"/institutions/{institution_id}/privileges/{uuid.uuid4()}",
        json={"price": 5},
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "PRIVILEGE_NOT_FOUND"}


async def test_purchase_flow_repeats_idempotently_and_out_of_stock(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    student_headers = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
    )
    await _accrue(client, institution_id, student_id, admin_headers, 60)
    privilege_id = await _create_privilege(
        client, institution_id, admin_headers, price=30, stock=1
    )
    operation_id = str(uuid.uuid4())

    first = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": operation_id,
            "privilege_id": privilege_id,
            "expected_price": 30,
        },
        headers=student_headers,
    )
    assert first.status_code == 201
    assert first.json()["status"] == "pending"

    second = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": operation_id,
            "privilege_id": privilege_id,
            "expected_price": 30,
        },
        headers=student_headers,
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    out_of_stock = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": privilege_id,
            "expected_price": 30,
        },
        headers=student_headers,
    )
    assert out_of_stock.status_code == 409
    assert out_of_stock.json() == {"detail": "OUT_OF_STOCK"}


async def test_purchase_with_insufficient_balance_and_price_changed(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    student_headers = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
    )
    privilege_id = await _create_privilege(
        client, institution_id, admin_headers, price=50
    )

    insufficient = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": privilege_id,
            "expected_price": 50,
        },
        headers=student_headers,
    )
    assert insufficient.status_code == 409
    assert insufficient.json() == {"detail": "INSUFFICIENT_BALANCE"}

    await client.patch(
        f"/institutions/{institution_id}/privileges/{privilege_id}",
        json={"price": 60},
        headers=admin_headers,
    )
    price_changed = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": privilege_id,
            "expected_price": 50,
        },
        headers=student_headers,
    )
    assert price_changed.status_code == 409
    assert price_changed.json() == {"detail": "PRICE_CHANGED"}


async def test_admin_fulfils_and_rejects_purchases(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    student_headers = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
    )
    await _accrue(client, institution_id, student_id, admin_headers, 60)
    privilege_id = await _create_privilege(
        client, institution_id, admin_headers, price=30
    )

    purchase = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": privilege_id,
            "expected_price": 30,
        },
        headers=student_headers,
    )
    purchase_id = purchase.json()["id"]

    forbidden = await client.post(
        f"/institutions/{institution_id}/purchases/{purchase_id}/fulfil",
        headers=student_headers,
    )
    assert forbidden.status_code == 403

    fulfilled = await client.post(
        f"/institutions/{institution_id}/purchases/{purchase_id}/fulfil",
        headers=admin_headers,
    )
    assert fulfilled.status_code == 200
    assert fulfilled.json()["status"] == "fulfilled"
    assert fulfilled.json()["user_id"] == student_id

    already_resolved = await client.post(
        f"/institutions/{institution_id}/purchases/{purchase_id}/reject",
        headers=admin_headers,
    )
    assert already_resolved.status_code == 409
    assert already_resolved.json() == {"detail": "PURCHASE_ALREADY_RESOLVED"}


async def test_reject_returns_balance_and_admin_sees_pending_queue(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    student_headers = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
    )
    await _accrue(client, institution_id, student_id, admin_headers, 60)
    privilege_id = await _create_privilege(
        client, institution_id, admin_headers, price=30
    )

    purchase = await client.post(
        f"/institutions/{institution_id}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": privilege_id,
            "expected_price": 30,
        },
        headers=student_headers,
    )
    purchase_id = purchase.json()["id"]

    pending = await client.get(
        f"/institutions/{institution_id}/purchases?status=pending",
        headers=admin_headers,
    )
    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()] == [purchase_id]

    rejected = await client.post(
        f"/institutions/{institution_id}/purchases/{purchase_id}/reject",
        headers=admin_headers,
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"

    balance = await client.get(
        f"/institutions/{institution_id}/me/currency", headers=student_headers
    )
    assert balance.json()["balance"] == 60

    my_purchases = await client.get(
        f"/institutions/{institution_id}/me/purchases", headers=student_headers
    )
    assert my_purchases.json()[0]["status"] == "rejected"


async def test_market_endpoints_require_matching_token_context(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    """Токен учреждения A на пути учреждения B — 403, а не доступ к чужому
    маркету (находка ревью: `check_role` сверяет только наличие
    учреждения в токене, но не путь; матч даёт только
    `require_institution_context`, как у остальных use case'ов).
    """
    admin_id = uuid.uuid4()
    institution_a = await _create_institution(client, token_factory(subject=admin_id))
    institution_b = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers_a = _headers(
        token_factory(subject=admin_id, institution_id=institution_a)
    )
    student_id = await _create_student(
        client, institution_a, admin_headers_a, token_factory
    )
    # Токен выпущен для A, путь запроса — B.
    student_headers_a = _headers(
        token_factory(subject=uuid.UUID(student_id), institution_id=institution_a)
    )

    list_privileges = await client.get(
        f"/institutions/{institution_b}/privileges", headers=student_headers_a
    )
    assert list_privileges.status_code == 403
    assert list_privileges.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}

    create_purchase = await client.post(
        f"/institutions/{institution_b}/purchases",
        json={
            "operation_id": str(uuid.uuid4()),
            "privilege_id": str(uuid.uuid4()),
            "expected_price": 10,
        },
        headers=student_headers_a,
    )
    assert create_purchase.status_code == 403
    assert create_purchase.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}

    list_my_purchases = await client.get(
        f"/institutions/{institution_b}/me/purchases", headers=student_headers_a
    )
    assert list_my_purchases.status_code == 403
    assert list_my_purchases.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}

    # Админский эндпоинт уже защищён `require_institution_admin` —
    # достаточно одного кейса, чтобы убедиться, что регресса нет.
    create_privilege = await client.post(
        f"/institutions/{institution_b}/privileges",
        json={"title": "Кофе", "price": 10},
        headers=admin_headers_a,
    )
    assert create_privilege.status_code == 403
    assert create_privilege.json() == {"detail": "INSTITUTION_CONTEXT_REQUIRED"}


async def test_market_is_isolated_between_institutions(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    institution_a = await _create_institution(client, token_factory(subject=admin_a))
    institution_b = await _create_institution(client, token_factory(subject=admin_b))
    headers_a = _headers(token_factory(subject=admin_a, institution_id=institution_a))
    headers_b = _headers(token_factory(subject=admin_b, institution_id=institution_b))
    privilege_id = await _create_privilege(client, institution_a, headers_a, price=10)

    cross_patch = await client.patch(
        f"/institutions/{institution_b}/privileges/{privilege_id}",
        json={"price": 5},
        headers=headers_b,
    )
    assert cross_patch.status_code == 404
    assert cross_patch.json() == {"detail": "PRIVILEGE_NOT_FOUND"}

    catalogue_b = await client.get(
        f"/institutions/{institution_b}/privileges", headers=headers_b
    )
    assert catalogue_b.json() == []
