"""Адаптер внутреннего выпуска токена users (раздел 4, вариант Р5-б).

Один ``httpx.AsyncClient`` на приложение — создаётся и закрывается в
``lifespan`` (``app/main.py``), сюда передаётся уже готовым. Таймаут на
весь запрос настраивается там же (2 с, раздел 4.6); ретраев внутри
gamification нет — повтор со стороны клиента безопасен.

Токен пользователя и служебный секрет никогда не логируются здесь —
только код ответа и его смысл.
"""

import logging
import uuid

import httpx

from app.business.domain.errors import (
    SubjectTokenRejectedError,
    TokenIssuerContractError,
    TokenIssuerUnavailableError,
)

logger = logging.getLogger(__name__)

INSTITUTION_CONTEXT_PATH = "/internal/tokens/institution-context"


class UsersTokenIssuer:
    """Вызывает закрытый внутренний эндпоинт users на выпуск токена."""

    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, service_secret: str
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._service_secret = service_secret

    async def issue_context_token(
        self, *, subject_token: str, institution_id: uuid.UUID, role: str
    ) -> str:
        """См. ``app.business.ports.TokenIssuer.issue_context_token``."""
        try:
            response = await self._client.post(
                f"{self._base_url}{INSTITUTION_CONTEXT_PATH}",
                json={
                    "subject_token": subject_token,
                    "institution_id": str(institution_id),
                    "role": role,
                },
                headers={"X-Service-Secret": self._service_secret},
            )
        except httpx.HTTPError:
            logger.error("Users token issuer is unreachable", exc_info=True)
            raise TokenIssuerUnavailableError from None

        if response.status_code == 200:
            try:
                body = response.json()
                access_token = body["access_token"]
                if not isinstance(access_token, str) or not access_token:
                    raise ValueError("access_token is not a non-empty string")
            except (ValueError, KeyError, TypeError):
                logger.error(
                    "Users returned a 200 response with a malformed body: status=%s",
                    response.status_code,
                )
                raise TokenIssuerContractError from None
            return access_token
        if response.status_code == 401:
            # SERVICE_AUTH_FAILED: авария на нашей стороне (секрет не
            # принят), а не на стороне предъявителя токена. Клиенту это
            # не 401/403 про его собственные права.
            logger.error("Service authentication with users was rejected")
            raise TokenIssuerUnavailableError
        if response.status_code == 403:
            # SUBJECT_TOKEN_REJECTED: предъявленный токен невалиден,
            # истёк, отозван, или пользователь неактивен.
            raise SubjectTokenRejectedError
        if response.status_code == 422:
            logger.error(
                "Users rejected the token issuance request as malformed: status=%s",
                response.status_code,
            )
            raise TokenIssuerContractError

        logger.error(
            "Unexpected response from users token issuer: status=%s",
            response.status_code,
        )
        raise TokenIssuerUnavailableError
