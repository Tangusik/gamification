"""API-тесты эндпоинтов валюты (Ч1 плана 06): коды ответов, идемпотентность,
видимость `/students` и `/groups` для преподавателя.
"""

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


async def _attach_student(
    client: AsyncClient,
    institution_id: str,
    group_id: str,
    student_id: str,
    admin_headers: dict,
) -> None:
    response = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/students/{student_id}",
        headers=admin_headers,
    )
    assert response.status_code == 204


async def _attach_teacher(
    client: AsyncClient,
    institution_id: str,
    group_id: str,
    teacher_id: str,
    admin_headers: dict,
) -> None:
    response = await client.put(
        f"/institutions/{institution_id}/groups/{group_id}/teachers/{teacher_id}",
        headers=admin_headers,
    )
    assert response.status_code == 204


async def _create_group(
    client: AsyncClient, institution_id: str, admin_headers: dict, name: str
) -> str:
    response = await client.post(
        f"/institutions/{institution_id}/groups",
        json={"name": name},
        headers=admin_headers,
    )
    assert response.status_code == 201
    return response.json()["id"]


async def test_get_my_currency_is_empty_by_default(
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

    response = await client.get(
        f"/institutions/{institution_id}/me/currency",
        headers=_headers(
            token_factory(subject=uuid.UUID(student_id), institution_id=institution_id)
        ),
    )

    assert response.status_code == 200
    assert response.json() == {"balance": 0, "transactions": []}


async def test_get_my_currency_forbidden_for_teacher_and_admin(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)

    admin_response = await client.get(
        f"/institutions/{institution_id}/me/currency", headers=admin_headers
    )
    teacher_response = await client.get(
        f"/institutions/{institution_id}/me/currency",
        headers=_headers(
            token_factory(subject=uuid.UUID(teacher_id), institution_id=institution_id)
        ),
    )

    for response in (admin_response, teacher_response):
        assert response.status_code == 403
        assert response.json() == {"detail": "INSUFFICIENT_ROLE"}


async def test_teacher_accrues_to_own_student_and_repeats_idempotently(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    group_id = await _create_group(client, institution_id, admin_headers, "Группа")
    await _attach_teacher(client, institution_id, group_id, teacher_id, admin_headers)
    await _attach_student(client, institution_id, group_id, student_id, admin_headers)
    teacher_headers = _headers(
        token_factory(subject=uuid.UUID(teacher_id), institution_id=institution_id)
    )
    operation_id = str(uuid.uuid4())

    first = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": operation_id, "amount": 50, "comment": "За олимпиаду"},
        headers=teacher_headers,
    )
    assert first.status_code == 201
    body = first.json()
    assert body["kind"] == "manual_accrual"
    assert body["amount"] == 50
    assert body["created_by_role"] == "teacher"
    assert body["reverses_id"] is None

    second = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": operation_id, "amount": 50, "comment": "За олимпиаду"},
        headers=teacher_headers,
    )
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]

    account = await client.get(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        headers=admin_headers,
    )
    assert account.status_code == 200
    assert account.json()["balance"] == 50
    assert len(account.json()["transactions"]) == 1


async def test_repeated_operation_id_with_different_amount_is_conflict(
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
    operation_id = str(uuid.uuid4())
    await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": operation_id, "amount": 10},
        headers=admin_headers,
    )

    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": operation_id, "amount": 20},
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "OPERATION_ID_CONFLICT"}


async def test_accrual_to_foreign_student_is_member_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    teacher_headers = _headers(
        token_factory(subject=uuid.UUID(teacher_id), institution_id=institution_id)
    )

    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 10},
        headers=teacher_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "MEMBER_NOT_FOUND"}


async def test_accrual_to_suspended_student_is_conflict(
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
    await client.patch(
        f"/institutions/{institution_id}/students/{student_id}",
        json={"status": "suspended"},
        headers=admin_headers,
    )

    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 10},
        headers=admin_headers,
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "STUDENT_SUSPENDED"}


async def test_amount_out_of_range_and_comment_too_long_are_422(
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

    too_much = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 10_001},
        headers=admin_headers,
    )
    zero = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 0},
        headers=admin_headers,
    )
    long_comment = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={
            "operation_id": str(uuid.uuid4()),
            "amount": 10,
            "comment": "x" * 201,
        },
        headers=admin_headers,
    )

    assert too_much.status_code == 422
    assert zero.status_code == 422
    assert long_comment.status_code == 422


async def test_comment_with_nul_byte_is_422_not_500(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    """NUL в комментарии — 422 по полю, а не 500 из драйвера БД (I1)."""
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )

    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={
            "operation_id": str(uuid.uuid4()),
            "amount": 10,
            "comment": "before\x00after",
        },
        headers=admin_headers,
    )

    assert response.status_code == 422


async def test_blank_comment_is_stored_as_null(
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

    response = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 10, "comment": "   "},
        headers=admin_headers,
    )

    assert response.status_code == 201
    assert response.json()["comment"] is None


async def test_admin_reverses_accrual_and_repeat_reverses_is_forbidden_for_teacher(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)
    student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    accrual = await client.post(
        f"/institutions/{institution_id}/students/{student_id}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 40},
        headers=admin_headers,
    )
    transaction_id = accrual.json()["id"]
    teacher_headers = _headers(
        token_factory(subject=uuid.UUID(teacher_id), institution_id=institution_id)
    )

    forbidden = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{transaction_id}/reversal",
        json={"operation_id": str(uuid.uuid4())},
        headers=teacher_headers,
    )
    assert forbidden.status_code == 403
    assert forbidden.json() == {"detail": "INSUFFICIENT_ROLE"}

    operation_id = str(uuid.uuid4())
    first = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{transaction_id}/reversal",
        json={"operation_id": operation_id},
        headers=admin_headers,
    )
    assert first.status_code == 201
    assert first.json()["kind"] == "reversal"
    assert first.json()["amount"] == -40

    second = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{transaction_id}/reversal",
        json={"operation_id": operation_id},
        headers=admin_headers,
    )
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]

    already_reversed = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{transaction_id}/reversal",
        json={"operation_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert already_reversed.status_code == 409
    assert already_reversed.json() == {"detail": "TRANSACTION_ALREADY_REVERSED"}

    reversal_id = first.json()["id"]
    reverse_the_reversal = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{reversal_id}/reversal",
        json={"operation_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    assert reverse_the_reversal.status_code == 404
    assert reverse_the_reversal.json() == {"detail": "TRANSACTION_NOT_FOUND"}


async def test_reversal_of_unknown_transaction_is_not_found(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )

    response = await client.post(
        f"/institutions/{institution_id}/currency-transactions/{uuid.uuid4()}/reversal",
        json={"operation_id": str(uuid.uuid4())},
        headers=admin_headers,
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "TRANSACTION_NOT_FOUND"}


async def test_teacher_sees_only_students_and_groups_of_own_group(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_id = uuid.uuid4()
    institution_id = await _create_institution(client, token_factory(subject=admin_id))
    admin_headers = _headers(
        token_factory(subject=admin_id, institution_id=institution_id)
    )
    teacher_id = await _create_teacher(client, app, institution_id, admin_headers)
    own_student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    other_student_id = await _create_student(
        client, institution_id, admin_headers, token_factory
    )
    own_group_id = await _create_group(
        client, institution_id, admin_headers, "Своя группа"
    )
    other_group_id = await _create_group(
        client, institution_id, admin_headers, "Чужая группа"
    )
    await _attach_teacher(
        client, institution_id, own_group_id, teacher_id, admin_headers
    )
    await _attach_student(
        client, institution_id, own_group_id, own_student_id, admin_headers
    )
    await _attach_student(
        client, institution_id, other_group_id, other_student_id, admin_headers
    )
    teacher_headers = _headers(
        token_factory(subject=uuid.UUID(teacher_id), institution_id=institution_id)
    )

    students = await client.get(
        f"/institutions/{institution_id}/students", headers=teacher_headers
    )
    assert students.status_code == 200
    student_ids = {item["user_id"] for item in students.json()}
    assert student_ids == {own_student_id}
    assert students.json()[0]["balance"] == 0

    groups = await client.get(
        f"/institutions/{institution_id}/groups", headers=teacher_headers
    )
    assert groups.status_code == 200
    assert [group["id"] for group in groups.json()] == [own_group_id]

    foreign_group_students = await client.get(
        f"/institutions/{institution_id}/students?group_id={other_group_id}",
        headers=teacher_headers,
    )
    assert foreign_group_students.status_code == 404
    assert foreign_group_students.json() == {"detail": "GROUP_NOT_FOUND"}


async def test_currency_is_isolated_between_institutions(
    client: AsyncClient, app: FastAPI, token_factory
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    institution_a = await _create_institution(client, token_factory(subject=admin_a))
    institution_b = await _create_institution(client, token_factory(subject=admin_b))
    headers_a = _headers(token_factory(subject=admin_a, institution_id=institution_a))
    headers_b = _headers(token_factory(subject=admin_b, institution_id=institution_b))
    student_a = await _create_student(client, institution_a, headers_a, token_factory)
    accrual = await client.post(
        f"/institutions/{institution_a}/students/{student_a}/currency-transactions",
        json={"operation_id": str(uuid.uuid4()), "amount": 10},
        headers=headers_a,
    )
    transaction_id = accrual.json()["id"]

    cross_read = await client.get(
        f"/institutions/{institution_b}/students/{student_a}/currency-transactions",
        headers=headers_b,
    )
    assert cross_read.status_code == 404
    assert cross_read.json() == {"detail": "MEMBER_NOT_FOUND"}

    cross_reversal = await client.post(
        f"/institutions/{institution_b}/currency-transactions/{transaction_id}/reversal",
        json={"operation_id": str(uuid.uuid4())},
        headers=headers_b,
    )
    assert cross_reversal.status_code == 404
    assert cross_reversal.json() == {"detail": "TRANSACTION_NOT_FOUND"}
