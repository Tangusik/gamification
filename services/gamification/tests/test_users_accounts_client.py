"""``UsersAccounts`` — единственный адаптер, знающий HTTP-контракт users на
создание аккаунта (В1/А1). Проверяется через ``httpx.MockTransport``, без
сети — по образцу ``tests/test_users_token_issuer.py``.
"""

import json
import uuid

import httpx
import pytest

from app.business.domain.errors import (
    EmailAlreadyRegisteredError,
    InvalidPasswordError,
    UsersContractError,
    UsersUnavailableError,
)
from app.clients.users_accounts import UsersAccounts

NEW_USER_ID = uuid.uuid4()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)


async def test_create_account_returns_user_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/users"
        assert request.headers["X-Service-Secret"] == "secret"
        body = json.loads(request.content)
        assert body == {"email": "teacher@example.com", "password": "s3cr3t-pass"}
        return httpx.Response(201, json={"id": str(NEW_USER_ID)})

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    user_id = await accounts.create_account(
        email="teacher@example.com", password="s3cr3t-pass"
    )

    assert user_id == NEW_USER_ID


async def test_create_account_sends_full_name_when_given() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {
            "email": "teacher@example.com",
            "password": "s3cr3t-pass",
            "full_name": "Иван",
        }
        return httpx.Response(201, json={"id": str(NEW_USER_ID)})

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    await accounts.create_account(
        email="teacher@example.com", password="s3cr3t-pass", full_name="Иван"
    )


async def test_create_account_omits_full_name_when_not_given() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "full_name" not in body
        return httpx.Response(201, json={"id": str(NEW_USER_ID)})

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    await accounts.create_account(email="teacher@example.com", password="s3cr3t-pass")


async def test_malformed_json_on_201_maps_to_contract_error() -> None:
    accounts = UsersAccounts(
        _client(lambda request: httpx.Response(201, text="not-json")),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersContractError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_missing_id_on_201_maps_to_contract_error() -> None:
    accounts = UsersAccounts(
        _client(lambda request: httpx.Response(201, json={})),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersContractError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_email_already_exists_maps_to_own_error() -> None:
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(409, json={"detail": "USER_ALREADY_EXISTS"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(EmailAlreadyRegisteredError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_password_rejected_maps_to_own_error() -> None:
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(400, json={"detail": "PASSWORD_REJECTED"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(InvalidPasswordError):
        await accounts.create_account(email="a@b.c", password="short")


async def test_service_auth_failure_maps_to_unavailable() -> None:
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(401, json={"detail": "SERVICE_AUTH_FAILED"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersUnavailableError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_validation_error_maps_to_contract_error() -> None:
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(422, json={"detail": "validation error"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersContractError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_network_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    with pytest.raises(UsersUnavailableError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_unexpected_status_maps_to_unavailable() -> None:
    accounts = UsersAccounts(
        _client(lambda request: httpx.Response(500, text="boom")),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersUnavailableError):
        await accounts.create_account(email="a@b.c", password="whatever123")


async def test_get_full_name_returns_name() -> None:
    target_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/internal/users/{target_id}"
        assert request.headers["X-Service-Secret"] == "secret"
        return httpx.Response(200, json={"id": str(target_id), "full_name": "Иван"})

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    assert await accounts.get_full_name(target_id) == "Иван"


async def test_get_full_name_returns_none_when_not_set() -> None:
    target_id = uuid.uuid4()
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(
                200, json={"id": str(target_id), "full_name": None}
            )
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    assert await accounts.get_full_name(target_id) is None


async def test_get_full_name_returns_none_on_404() -> None:
    accounts = UsersAccounts(
        _client(lambda request: httpx.Response(404)),
        base_url="http://users:8000",
        service_secret="secret",
    )

    assert await accounts.get_full_name(uuid.uuid4()) is None


async def test_get_full_name_malformed_body_maps_to_contract_error() -> None:
    accounts = UsersAccounts(
        _client(lambda request: httpx.Response(200, text="not-json")),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersContractError):
        await accounts.get_full_name(uuid.uuid4())


async def test_get_full_name_network_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    accounts = UsersAccounts(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    with pytest.raises(UsersUnavailableError):
        await accounts.get_full_name(uuid.uuid4())


async def test_get_full_name_service_auth_failure_maps_to_unavailable() -> None:
    accounts = UsersAccounts(
        _client(
            lambda request: httpx.Response(401, json={"detail": "SERVICE_AUTH_FAILED"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(UsersUnavailableError):
        await accounts.get_full_name(uuid.uuid4())
