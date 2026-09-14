"""``UsersTokenIssuer`` — единственный адаптер, знающий HTTP-контракт users
(раздел 4.2). Проверяется через ``httpx.MockTransport``, без сети.
"""

import json
import uuid

import httpx
import pytest

from app.business.domain.errors import (
    SubjectTokenRejectedError,
    TokenIssuerContractError,
    TokenIssuerUnavailableError,
)
from app.clients.users_tokens import UsersTokenIssuer

INSTITUTION_ID = uuid.uuid4()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=2.0)


async def test_issue_context_token_returns_access_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/internal/tokens/institution-context"
        assert request.headers["X-Service-Secret"] == "secret"
        body = json.loads(request.content)
        assert body == {
            "subject_token": "T0",
            "institution_id": str(INSTITUTION_ID),
            "role": "student",
        }
        return httpx.Response(200, json={"access_token": "T1", "token_type": "bearer"})

    issuer = UsersTokenIssuer(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    token = await issuer.issue_context_token(
        subject_token="T0", institution_id=INSTITUTION_ID, role="student"
    )

    assert token == "T1"


async def test_malformed_json_on_200_maps_to_contract_error() -> None:
    issuer = UsersTokenIssuer(
        _client(lambda request: httpx.Response(200, text="not-json")),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(TokenIssuerContractError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_missing_access_token_on_200_maps_to_contract_error() -> None:
    issuer = UsersTokenIssuer(
        _client(lambda request: httpx.Response(200, json={"token_type": "bearer"})),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(TokenIssuerContractError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_service_auth_failure_maps_to_unavailable() -> None:
    issuer = UsersTokenIssuer(
        _client(
            lambda request: httpx.Response(401, json={"detail": "SERVICE_AUTH_FAILED"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(TokenIssuerUnavailableError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_subject_token_rejected_maps_to_own_error() -> None:
    issuer = UsersTokenIssuer(
        _client(
            lambda request: httpx.Response(
                403, json={"detail": "SUBJECT_TOKEN_REJECTED"}
            )
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(SubjectTokenRejectedError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_validation_error_maps_to_contract_error() -> None:
    issuer = UsersTokenIssuer(
        _client(
            lambda request: httpx.Response(422, json={"detail": "validation error"})
        ),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(TokenIssuerContractError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_network_error_maps_to_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    issuer = UsersTokenIssuer(
        _client(handler), base_url="http://users:8000", service_secret="secret"
    )

    with pytest.raises(TokenIssuerUnavailableError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )


async def test_unexpected_status_maps_to_unavailable() -> None:
    issuer = UsersTokenIssuer(
        _client(lambda request: httpx.Response(500, text="boom")),
        base_url="http://users:8000",
        service_secret="secret",
    )

    with pytest.raises(TokenIssuerUnavailableError):
        await issuer.issue_context_token(
            subject_token="T0", institution_id=INSTITUTION_ID, role="student"
        )
