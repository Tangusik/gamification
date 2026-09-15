"""Порты бизнес-слоя сервиса users (план 10-refresh).

По образцу ``app/business/ports.py`` сервиса gamification: контракты,
которыми бизнес-слой типизирует свои зависимости от внешнего мира
(хранилище, соседние сервисы), реализации которых лежат в
``app.repositories``/``app.clients`` и умеют импортировать этот модуль
(обратное направление запрещено — см. ``tests/test_business_imports.py``).

Единственный порт на этом этапе — ``RefreshSessionRepository``:
атомарность ротации (У2) и развилка «новый / grace / повтор» (вопрос 3)
— обязанность реализации, а не вызывающего кода: только она способна
гарантировать её одинаково для PostgreSQL (одна транзакция) и in-memory
(блокировка на сессию).
"""

import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from app.business.domain.entities import RefreshSession


class RotationOutcome(StrEnum):
    """Исход попытки ротации refresh-токена (У2, вопрос 3)."""

    ROTATED = "rotated"
    REUSED = "reused"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class RotationResult:
    """Результат ``RefreshSessionRepository.rotate``.

    ``session`` и ``raw_token`` заполнены только при ``ROTATED``.
    При ``REUSED`` сессия уже погашена самим репозиторием — она
    возвращается сюда только для аудит-лога вызывающим кодом.
    """

    outcome: RotationOutcome
    session: RefreshSession | None = None
    # ``repr=False`` (I1, ревью Ч3): сырой токен не должен попадать в
    # логи и трейсбеки через дефолтный ``repr`` датакласса.
    raw_token: str | None = field(default=None, repr=False)


class RefreshSessionRepository(Protocol):
    """Хранилище refresh-сессий и их цепочек токенов (У1, план 10-refresh).

    Сырой токен доверяется репозиторию только на вход/выход операций —
    хранится и ищется исключительно его хеш (``hash_refresh_token``).
    """

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        client: str,
        institution_id: uuid.UUID | None,
        idle_ttl: timedelta,
        absolute_ttl: timedelta,
    ) -> tuple[RefreshSession, str]:
        """Завести новую сессию с первым токеном её цепочки.

        Возвращает сессию и сырой токен — второй раз сырое значение
        получить неоткуда, хранится только его хеш.
        """
        ...

    async def find(self, token_hash: str) -> RefreshSession | None:
        """Найти сессию по хешу токена, без блокировки (У3, шаг 1).

        ``None`` — токен неизвестен: удалён, никогда не существовал,
        либо принадлежит уже забытой ротацией строке.
        """
        ...

    async def rotate(
        self,
        *,
        token_hash: str,
        idle_ttl: timedelta,
        reuse_grace: timedelta,
        institution_id: uuid.UUID | None,
    ) -> RotationResult:
        """Атомарно провернуть ротацию предъявленного токена.

        ``institution_id`` — уже вычисленное вызывающим кодом значение
        для записи в сессию (вопросы 1 и 2 решаются до вызова, вне
        транзакции — У3): при недоступности gamification передаётся
        текущее значение сессии без изменений, при 404 — ``None``.
        """
        ...

    async def release(self) -> None:
        """Закрыть текущую транзакцию чтения (У3, L2 ревью Ч3).

        Вызывается после ``find`` и всех проверок, выполненных на его
        результате, но до сетевого обращения в gamification: без этого
        соединение висит «idle in transaction» на время HTTP-вызова
        (до 2 с), и при недоступности gamification исчерпывается пул.
        Для in-memory реализации это no-op — отдельной транзакции там
        нет.
        """
        ...

    async def revoke(self, session_id: uuid.UUID, *, reason: str) -> None:
        """Погасить сессию по идентификатору."""
        ...

    async def revoke_for_user(self, user_id: uuid.UUID, *, reason: str) -> None:
        """Погасить все сессии пользователя (вопрос 5 — смена пароля)."""
        ...

    async def revoke_by_token(self, token_hash: str, *, reason: str) -> None:
        """Погасить сессию по любому токену её цепочки.

        В том числе уже использованному (У10 — logout принимает и
        погашенный токен цепочки).
        """
        ...

    async def delete_expired_for_user(self, user_id: uuid.UUID) -> None:
        """Удалить просроченные строки сессий пользователя (У11).

        Планировщика нет: чистка происходит при входе пользователя.
        """
        ...
