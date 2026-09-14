"""Db-тест гонки: два параллельных принятия одноразового приглашения (раздел 5).

Доказывает атомарность принятия — блокировка строки приглашения
(``SELECT ... FOR UPDATE``) не даёт двум параллельным запросам оба
увидеть ``uses_count = 0``. Требует поднятого docker-стека и
``GAMIFICATION_TEST_DATABASE_URL`` — без переменной пропускается
``tests/db/conftest.py``.
"""

import asyncio
import uuid
from datetime import UTC, datetime

from app.business.domain.access_errors import InvitationInvalidError
from app.business.domain.enums import InstitutionKind
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import AcceptInvitation, CreateInvitation
from app.repositories.database import create_session_factory
from app.repositories.uow import SqlAlchemyUnitOfWork
from tests.contract.conftest import postgres_schema


class _FixedClock:
    """Часы для db-теста: use case'ам всё равно, откуда взято время."""

    def now(self) -> datetime:
        return datetime.now(UTC)


async def test_two_parallel_accepts_of_one_time_invitation_yield_one_membership(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        clock = _FixedClock()

        setup_uow = SqlAlchemyUnitOfWork(session_factory)
        admin_id = uuid.uuid4()
        institution = await CreateInstitution(setup_uow, clock).execute(
            name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=admin_id
        )
        invitation = await CreateInvitation(setup_uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            max_uses=1,
        )

        user_a, user_b = uuid.uuid4(), uuid.uuid4()

        async def accept(user_id: uuid.UUID):
            uow = SqlAlchemyUnitOfWork(session_factory)
            return await AcceptInvitation(uow, clock).execute(
                user_id=user_id, token=invitation.token
            )

        results = await asyncio.gather(
            accept(user_a), accept(user_b), return_exceptions=True
        )

        successes = [result for result in results if not isinstance(result, Exception)]
        failures = [result for result in results if isinstance(result, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], InvitationInvalidError)

        verify_uow = SqlAlchemyUnitOfWork(session_factory)
        async with verify_uow as uow:
            scope = await uow.for_institution(institution.id)
            stored_invitation = await scope.invitations.get(invitation.id)
            memberships = [
                membership
                for user_id in (user_a, user_b)
                if (membership := await scope.memberships.get_for_user(user_id))
                is not None
            ]

        assert stored_invitation is not None
        assert stored_invitation.uses_count == 1
        assert len(memberships) == 1
