"""Actor — предъявитель проверенного access-токена."""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Actor:
    """Личность и контекст запроса, извлечённые из access-токена.

    Роль в токене намеренно не читается (раздел 3 плана): решение о
    доступе принимает хранилище членств, а не claim ``role`` — тот же
    принцип, что и в users, поэтому отзыв роли действует немедленно.

    ``raw_token`` — предъявленный токен целиком. Нужен переключению
    учреждения (раздел 4, B1): gamification пересылает его users как
    ``subject_token``, доказательство того, что пользователь сам к ней
    пришёл. Токен не логируется нигде дальше по цепочке.
    """

    user_id: uuid.UUID
    institution_id: uuid.UUID | None
    token_id: str | None
    raw_token: str
