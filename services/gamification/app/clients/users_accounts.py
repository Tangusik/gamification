"""Адаптер внутреннего создания аккаунта в users (В1/А1, раздел «Ч2» плана).

Тот же ``httpx.AsyncClient`` на приложение, что и у
``app.clients.users_tokens`` — создаётся и закрывается в ``lifespan``,
сюда передаётся уже готовым. Тот же таймаут (2 с) и тот же заголовок
служебного секрета.

Email и пароль никогда не логируются здесь — только код ответа и его
смысл.
"""

import logging
import uuid

import httpx

from app.business.domain.errors import (
    EmailAlreadyRegisteredError,
    InvalidPasswordError,
    UsersContractError,
    UsersUnavailableError,
)

logger = logging.getLogger(__name__)

CREATE_ACCOUNT_PATH = "/internal/users"


class UsersAccounts:
    """Вызывает закрытый внутренний эндпоинт users на создание аккаунта."""

    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, service_secret: str
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._service_secret = service_secret

    async def create_account(self, *, email: str, password: str) -> uuid.UUID:
        """См. ``app.business.ports.UserAccounts.create_account``."""
        try:
            response = await self._client.post(
                f"{self._base_url}{CREATE_ACCOUNT_PATH}",
                json={"email": email, "password": password},
                headers={"X-Service-Secret": self._service_secret},
            )
        except httpx.HTTPError:
            logger.error("Users account creation is unreachable", exc_info=True)
            raise UsersUnavailableError from None

        if response.status_code == 201:
            try:
                body = response.json()
                user_id = uuid.UUID(str(body["id"]))
            except (ValueError, KeyError, TypeError):
                logger.error(
                    "Users returned a 201 response with a malformed body: status=%s",
                    response.status_code,
                )
                raise UsersContractError from None
            return user_id
        if response.status_code == 409:
            raise EmailAlreadyRegisteredError
        if response.status_code == 400:
            raise InvalidPasswordError
        if response.status_code == 401:
            # Авария на нашей стороне (служебный секрет не принят), а не
            # отказ клиенту в правах — тот же принцип, что у UsersTokenIssuer.
            logger.error("Service authentication with users was rejected")
            raise UsersUnavailableError
        if response.status_code == 422:
            logger.error(
                "Users rejected the account creation request as malformed: status=%s",
                response.status_code,
            )
            raise UsersContractError

        logger.error(
            "Unexpected response from users account creation: status=%s",
            response.status_code,
        )
        raise UsersUnavailableError
