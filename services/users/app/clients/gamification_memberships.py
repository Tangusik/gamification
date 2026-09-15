"""Клиент users → gamification: проверка членства при refresh.

По образцу ``UsersTokenIssuer`` из сервиса gamification
(``app/clients/users_tokens.py`` там) — тот же httpx-клиент, тот же
таймаут (2 с, раздел 4.6 плана 03) и то же правило: токен пользователя и
служебный секрет никогда не логируются, только код ответа и его смысл.

Контракт вызываемого эндпоинта — ``POST /internal/memberships/resolve``
(раздел 3 плана 10-refresh, реализует Ч2): тело
``{user_id, institution_id}``, 200 ``{role}``, 404
``MEMBERSHIP_NOT_ACTIVE``, 401 ``SERVICE_AUTH_FAILED``, 422 — дефект
контракта. Все ветки отказа, кроме 404, сведены к одному исходу
(вопрос 2 = А): вызывающий use case выдаёт access без контекста.
"""

import logging
import uuid

import httpx

from app.business.domain.errors import (
    MembershipCheckUnavailableError,
    MembershipNotActiveError,
)

logger = logging.getLogger(__name__)

RESOLVE_PATH = "/internal/memberships/resolve"


class GamificationMembershipsClient:
    """Вызывает закрытый внутренний эндпоинт gamification на проверку членства."""

    def __init__(
        self, client: httpx.AsyncClient, *, base_url: str, service_secret: str
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._service_secret = service_secret

    async def resolve_role(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID
    ) -> str:
        """См. ``app.business.use_cases.refresh.MembershipsPort.resolve_role``."""
        try:
            response = await self._client.post(
                f"{self._base_url}{RESOLVE_PATH}",
                json={
                    "user_id": str(user_id),
                    "institution_id": str(institution_id),
                },
                headers={"X-Service-Secret": self._service_secret},
            )
        except (httpx.HTTPError, httpx.InvalidURL):
            # ``InvalidURL`` не наследует ``HTTPError``: сюда попадает и
            # незаданный ``USERS_GAMIFICATION_INTERNAL_URL`` (пустой
            # адрес даёт относительный URL) — конфигурационный дефект
            # обязан вести к той же ветке «недоступна» (вопрос 2 = А), а
            # не к 500.
            logger.error("Gamification memberships check is unreachable", exc_info=True)
            raise MembershipCheckUnavailableError from None

        if response.status_code == 200:
            try:
                body = response.json()
                role = body["role"]
                if not isinstance(role, str) or not role:
                    raise ValueError("role is not a non-empty string")
            except (ValueError, KeyError, TypeError):
                logger.error(
                    "Gamification returned a 200 response with a malformed "
                    "body: status=%s",
                    response.status_code,
                )
                raise MembershipCheckUnavailableError from None
            return role

        if response.status_code == 404:
            # MEMBERSHIP_NOT_ACTIVE: членства нет, оно приостановлено, либо
            # учреждения не существует — один код на все три случая.
            raise MembershipNotActiveError

        # 401 SERVICE_AUTH_FAILED, 422 (дефект контракта) и любой другой
        # неожиданный статус — авария на нашей стороне, а не отказ в правах
        # конкретному пользователю (вопрос 2 = А).
        logger.error(
            "Membership check was rejected or failed: status=%s",
            response.status_code,
        )
        raise MembershipCheckUnavailableError
