"""Состав access-токена платформы.

Формат claims — общий контракт всех сервисов, поэтому он описан здесь,
а не в каждом сервисе отдельно: разъехавшись, он перестаёт быть
контрактом.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Claims, без которых токен не принимается. ``exp`` в этом списке —
# решение проекта, а не умолчание библиотеки: PyJWT проверяет срок,
# только если ``exp`` в токене есть, и валидно подписанный токен без
# срока приняли бы бессрочно.
REQUIRED_CLAIMS = ("exp", "sub")


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Разобранная нагрузка access-токена.

    ``role`` и ``institution_id`` — активный контекст: токен выпускается
    в контексте одного учреждения, смена учреждения означает перевыпуск
    токена. Оба могут быть ``None`` — у владельца инсталляции членства
    в учреждении нет.

    ``token_id`` (claim ``jti``) идентифицирует конкретный выпущенный
    токен и нужен отзыву. ``None`` означает токен, выпущенный до
    введения ``jti``, — отозвать такой поштучно нельзя.
    """

    subject: str
    expires_at: datetime
    token_id: str | None
    role: str | None
    institution_id: str | None
    raw: Mapping[str, Any]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AccessTokenClaims":
        """Собрать claims из проверенной нагрузки токена."""
        return cls(
            subject=str(payload["sub"]),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            token_id=payload.get("jti"),
            role=payload.get("role"),
            institution_id=payload.get("institution_id"),
            raw=payload,
        )
