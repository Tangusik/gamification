"""L1 (ревью Ч3) на настоящей PostgreSQL: устаревание identity map.

``Session.get(..., with_for_update=True)`` без ``populate_existing=True``
возвращает объект из identity map без повторного запроса, если строка
уже была загружена в этой же сессии (например, ``find()`` в роутере до
сетевого вызова в gamification). На in-memory адаптере этот дефект
невоспроизводим: там нет отдельной транзакции и идентити-мапа поверх
БД, состояние всегда общее и живое, — поэтому тест возможен только
здесь, против реальной PostgreSQL.
"""

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.business.domain.entities import hash_refresh_token
from app.business.ports import RotationOutcome
from app.repositories.sql_alchemy import (
    SqlAlchemyRefreshSessionRepository,
    SqlAlchemyUserRepository,
)

IDLE_TTL = timedelta(days=7)
ABSOLUTE_TTL = timedelta(days=30)
GRACE = timedelta(seconds=30)


async def test_rotate_sees_revocation_committed_between_find_and_rotate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Сессия отозвана другим соединением между ``find`` и ``rotate``.

    Воспроизводит окно У3: ``find`` читает и заполняет identity map,
    затем (в реальном коде — во время HTTP-вызова в gamification)
    logout или смена пароля из параллельного запроса гасят сессию и
    коммитят. ``rotate`` использует то же соединение и ту же identity
    map, что и ``find`` — без ``populate_existing=True`` он не увидел бы
    отзыв и выдал бы новый access-токен по уже погашенной сессии.
    """
    async with session_factory() as session_a:
        user = await SqlAlchemyUserRepository(session_a).create(
            {"email": "l1-marker@example.com", "hashed_password": "x"}
        )
        repo_a = SqlAlchemyRefreshSessionRepository(session_a)
        session, raw_token = await repo_a.create(
            user_id=user.id,
            client="web",
            institution_id=None,
            idle_ttl=IDLE_TTL,
            absolute_ttl=ABSOLUTE_TTL,
        )
        token_hash = hash_refresh_token(raw_token)

        # Заполняет identity map соединения ``session_a`` — то же самое,
        # что делает роутер до вызова gamification (У3, шаг 1-2).
        found = await repo_a.find(token_hash)
        assert found is not None
        await repo_a.release()

        # Другое соединение гасит сессию независимо и коммитит — как
        # logout или смена пароля из параллельного запроса.
        async with session_factory() as session_b:
            await SqlAlchemyRefreshSessionRepository(session_b).revoke(
                session.id, reason="logout"
            )

        result = await repo_a.rotate(
            token_hash=token_hash,
            idle_ttl=IDLE_TTL,
            reuse_grace=GRACE,
            institution_id=None,
        )

    assert result.outcome is RotationOutcome.NOT_FOUND
    assert result.raw_token is None
