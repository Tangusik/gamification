"""Db-тесты ограничений схемы групп (Ч2б): уникальность имени без учёта
регистра и первичный ключ-пара в ``group_students``/``group_teachers``.

Требуют поднятого docker-стека и ``GAMIFICATION_TEST_DATABASE_URL`` — без
переменной пропускаются ``tests/db/conftest.py``.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from app.business.domain.entities import Group, Institution, Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import GroupNameTakenError
from app.repositories.database import create_session_factory
from app.repositories.models import GroupStudentModel
from app.repositories.sql_alchemy import (
    SqlAlchemyGroupRepository,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
)
from tests.contract.conftest import postgres_schema
from tests.db.conftest import set_institution_context


async def test_group_name_unique_index_rejects_case_variant(db_env: str) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            institution = Institution(
                id=uuid.uuid4(),
                name="Школа №1",
                kind=InstitutionKind.SCHOOL,
                created_by=uuid.uuid4(),
                created_at=datetime.now(UTC),
            )
            await SqlAlchemyInstitutionRepository(session).add(institution)
            await session.commit()

            await set_institution_context(session, institution.id)
            group_repo = SqlAlchemyGroupRepository(session, institution.id)
            await group_repo.add(
                Group(
                    id=uuid.uuid4(),
                    institution_id=institution.id,
                    name="Кружок",
                    created_at=datetime.now(UTC),
                )
            )
            await session.commit()

            await set_institution_context(session, institution.id)
            try:
                await group_repo.add(
                    Group(
                        id=uuid.uuid4(),
                        institution_id=institution.id,
                        name="кружок",
                        created_at=datetime.now(UTC),
                    )
                )
                raised = None
            except GroupNameTakenError as error:
                raised = error
            assert raised is not None


async def test_group_students_primary_key_is_a_pair(db_env: str) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        async with session_factory() as session:
            institution = Institution(
                id=uuid.uuid4(),
                name="Школа №1",
                kind=InstitutionKind.SCHOOL,
                created_by=uuid.uuid4(),
                created_at=datetime.now(UTC),
            )
            await SqlAlchemyInstitutionRepository(session).add(institution)
            await session.commit()

            await set_institution_context(session, institution.id)
            membership_repo = SqlAlchemyInstitutionMemberships(session, institution.id)
            student = Membership(
                id=uuid.uuid4(),
                user_id=uuid.uuid4(),
                institution_id=institution.id,
                role=UserRole.STUDENT,
                status=MembershipStatus.ACTIVE,
                created_at=datetime.now(UTC),
            )
            await membership_repo.add(student)
            await session.commit()

            # Контекст выставлен заново — каждый ``commit()`` выше
            # завершает транзакцию и сбрасывает ``set_config(..., true)``
            # (ловушка A1, риск 2 плана 07a).
            await set_institution_context(session, institution.id)
            group_repo = SqlAlchemyGroupRepository(session, institution.id)
            group = Group(
                id=uuid.uuid4(),
                institution_id=institution.id,
                name="Группа",
                created_at=datetime.now(UTC),
            )
            await group_repo.add(group)
            await session.commit()

            await set_institution_context(session, institution.id)
            await session.execute(
                insert(GroupStudentModel).values(
                    group_id=group.id, membership_id=student.id
                )
            )
            await session.commit()

            await set_institution_context(session, institution.id)
            duplicate_rejected = False
            try:
                async with session.begin_nested():
                    await session.execute(
                        insert(GroupStudentModel).values(
                            group_id=group.id, membership_id=student.id
                        )
                    )
            except IntegrityError:
                duplicate_rejected = True
            assert duplicate_rejected
