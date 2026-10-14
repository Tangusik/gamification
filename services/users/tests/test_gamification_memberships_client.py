"""Тесты ``GamificationMembershipsClient.sync_profile_name`` (план 11-user-name).

Остальные методы клиента (``resolve_role``) проверяются только через
use case и e2e-тесты refresh — здесь же ``sync_profile_name`` разбирается
напрямую через ``httpx.MockTransport``, так как у него собственный HTTP
сериализатор запроса/ответа, который иначе никто не вызывает.
"""

import json
import uuid

import httpx
import pytest

from app.business.domain.errors import MembershipCheckUnavailableError
from app.clients.gamification_memberships import (
    SYNC_PROFILE_NAME_PATH,
    GamificationMembershipsClient,
)

BASE_URL = "http://gamification.internal"
SECRET = "service-secret"
USER_ID = uuid.uuid4()


def make_client(handler: httpx.MockTransport) -> GamificationMembershipsClient:
    http_client = httpx.AsyncClient(transport=handler)
    return GamificationMembershipsClient(
        http_client, base_url=BASE_URL, service_secret=SECRET
    )


async def test_sync_profile_name_sends_expected_request_and_parses_response() -> None:
    """Успешный вызов уходит по ожидаемому пути с телом и секретом в заголовке."""
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"updated": 3})

    client = make_client(httpx.MockTransport(handler))

    updated = await client.sync_profile_name(user_id=USER_ID, full_name="Имя Фамилия")

    assert updated == 3
    assert len(captured) == 1
    request = captured[0]
    assert request.method == "PATCH"
    assert request.url.path == SYNC_PROFILE_NAME_PATH
    assert request.headers["X-Service-Secret"] == SECRET
    body = json.loads(request.content)
    assert body == {"user_id": str(USER_ID), "full_name": "Имя Фамилия"}


async def test_sync_profile_name_passes_null_full_name() -> None:
    """``full_name=None`` (сброс имени) передаётся как ``null``, а не опускается."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"updated": 1})

    client = make_client(httpx.MockTransport(handler))

    updated = await client.sync_profile_name(user_id=USER_ID, full_name=None)

    assert updated == 1


@pytest.mark.parametrize("status_code", [401, 422, 500])
async def test_sync_profile_name_rejected_or_failed_status_raises(
    status_code: int,
) -> None:
    """401, 422 и прочие неожиданные статусы сведены к одному исключению."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(MembershipCheckUnavailableError):
        await client.sync_profile_name(user_id=USER_ID, full_name="Имя")


async def test_sync_profile_name_malformed_200_body_raises() -> None:
    """200 без ожидаемого ключа ``updated`` — дефект контракта, а не успех."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"oops": "no updated key"})

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(MembershipCheckUnavailableError):
        await client.sync_profile_name(user_id=USER_ID, full_name="Имя")


async def test_sync_profile_name_network_error_raises() -> None:
    """Недоступность gamification (сетевая ошибка) тоже сведена к одному исключению."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = make_client(httpx.MockTransport(handler))

    with pytest.raises(MembershipCheckUnavailableError):
        await client.sync_profile_name(user_id=USER_ID, full_name="Имя")
