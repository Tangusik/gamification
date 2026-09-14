"""Db-тесты RLS и разделения ролей PostgreSQL (раздел 5 плана `07a-rls.md`).

Требуют поднятого docker-стека и **обоих** DSN:
``GAMIFICATION_TEST_DATABASE_URL`` (роль приложения ``gamification_app``,
под ней открываются проверяемые соединения) и
``GAMIFICATION_TEST_OWNER_DATABASE_URL`` (роль-владелец ``gamification``,
которой ``postgres_schema`` строит схему миграцией — В4/P2). Без
переменных пропускаются ``tests/db/conftest.py``. Команда прогона — в
``.claude/plans/07a-rls.md``, раздел 5.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.pool import StaticPool

from app.business.domain.entities import Group, Institution, Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.repositories.database import create_engine, create_session_factory
from app.repositories.sql_alchemy import (
    SqlAlchemyGroupRepository,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
    SqlAlchemyInvitationLookup,
    SqlAlchemyUserMemberships,
)
from app.repositories.uow import SqlAlchemyUnitOfWork
from tests.contract.conftest import postgres_schema
from tests.db.conftest import set_institution_context

# Список таблиц задан явно (раздел 5 плана): новая RLS-таблица, забытая
# здесь, роняет тест первым же пунктом, а не тихо остаётся без политики.
RLS_TABLES = (
    "memberships",
    "invitations",
    "groups",
    "currency_transactions",
    "currency_balances",
    "group_students",
    "group_teachers",
    "privileges",
    "purchases",
)


def _new_institution(**overrides: object) -> Institution:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Institution(**defaults)  # type: ignore[arg-type]


def _new_membership(**overrides: object) -> Membership:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Membership(**defaults)  # type: ignore[arg-type]


async def _seed_institution(session_factory) -> Institution:
    async with session_factory() as session:
        institution = _new_institution()
        await SqlAlchemyInstitutionRepository(session).add(institution)
        await session.commit()
    return institution


async def test_rls_enabled_forced_and_policied_on_every_table(db_env: str) -> None:
    """Раздел 5, пункт 1: ``relrowsecurity``/``relforcerowsecurity`` и политика."""
    async with postgres_schema(db_env) as engine:
        async with engine.connect() as connection:
            for table in RLS_TABLES:
                row = (
                    await connection.execute(
                        text(
                            "SELECT relrowsecurity, relforcerowsecurity "
                            "FROM pg_class WHERE oid = (:table)::regclass"
                        ),
                        {"table": table},
                    )
                ).one()
                assert row.relrowsecurity is True, f"{table}: ENABLE не выставлен"
                assert row.relforcerowsecurity is True, f"{table}: FORCE не выставлен"

                policy_count = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM pg_policies WHERE tablename = :table"
                        ),
                        {"table": table},
                    )
                ).scalar_one()
                assert policy_count >= 1, f"{table}: политики нет"

            # В2/I0 — на institutions RLS нет (в таблице нет institution_id,
            # сама она арендатор).
            no_rls = (
                await connection.execute(
                    text(
                        "SELECT relrowsecurity FROM pg_class "
                        "WHERE oid = 'institutions'::regclass"
                    )
                )
            ).scalar_one()
            assert no_rls is False


async def test_select_without_context_sees_nothing_and_insert_fails_check(
    db_env: str,
) -> None:
    """Раздел 5, пункт 2: без контекста ``SELECT`` — 0 строк, ``INSERT`` падает."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution = await _seed_institution(session_factory)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            membership_repo = SqlAlchemyInstitutionMemberships(session, institution.id)
            seeded = _new_membership(institution_id=institution.id)
            await membership_repo.add(seeded)
            await session.commit()

        async with session_factory() as session:
            # Контекст не выставлен — политика фильтрует всё (fail-closed).
            statement = text("SELECT count(*) FROM memberships")
            count = (await session.execute(statement)).scalar_one()
            assert count == 0

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO memberships "
                        "(id, user_id, institution_id, role, status, created_at) "
                        "VALUES (:id, :user_id, :institution_id, :role, :status, now())"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": str(uuid.uuid4()),
                        "institution_id": str(institution.id),
                        "role": "student",
                        "status": "active",
                    },
                )
            await session.rollback()


async def test_privileges_select_without_context_sees_nothing_and_insert_fails_check(
    db_env: str,
) -> None:
    """Раздел 5, пункт 2 (план 07, инструкция 3): та же проверка для
    ``privileges`` — новой RLS-таблицы этапа маркета.
    """
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution = await _seed_institution(session_factory)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            await session.execute(
                text(
                    "INSERT INTO privileges "
                    "(id, institution_id, title, price, is_active, "
                    "created_at, updated_at) "
                    "VALUES (:id, :institution_id, 'Кофе', 10, true, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "institution_id": str(institution.id)},
            )
            await session.commit()

        async with session_factory() as session:
            # Контекст не выставлен — политика фильтрует всё (fail-closed).
            count = (
                await session.execute(text("SELECT count(*) FROM privileges"))
            ).scalar_one()
            assert count == 0

            with pytest.raises(DBAPIError):
                await session.execute(
                    text(
                        "INSERT INTO privileges "
                        "(id, institution_id, title, price, is_active, "
                        "created_at, updated_at) "
                        "VALUES (:id, :institution_id, 'Чай', 5, true, now(), now())"
                    ),
                    {"id": str(uuid.uuid4()), "institution_id": str(institution.id)},
                )
            await session.rollback()


async def test_context_a_does_not_see_rows_of_institution_b_via_link_tables(
    db_env: str,
) -> None:
    """Раздел 5, пункт 3: изоляция арендаторов, включая таблицы связей."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution_a = await _seed_institution(session_factory)
        institution_b = await _seed_institution(session_factory)

        async with session_factory() as session:
            await set_institution_context(session, institution_a.id)
            student_a = _new_membership(institution_id=institution_a.id)
            await SqlAlchemyInstitutionMemberships(session, institution_a.id).add(
                student_a
            )
            group_a = Group(
                id=uuid.uuid4(),
                institution_id=institution_a.id,
                name="Группа А",
                created_at=datetime.now(UTC),
            )
            await SqlAlchemyGroupRepository(session, institution_a.id).add(group_a)
            await session.commit()

            await set_institution_context(session, institution_a.id)
            await SqlAlchemyGroupRepository(session, institution_a.id).add_student(
                group_id=group_a.id, membership_id=student_a.id
            )
            await session.commit()

        async with session_factory() as session:
            await set_institution_context(session, institution_b.id)
            memberships = SqlAlchemyInstitutionMemberships(session, institution_b.id)
            assert await memberships.get_for_user(student_a.user_id) is None

            groups_b = SqlAlchemyGroupRepository(session, institution_b.id)
            assert await groups_b.get(group_a.id) is None
            # Таблица связей — через EXISTS по groups (У4): чужая группа
            # не видна, поэтому и её ученики не видны через group_students.
            assert await groups_b.list_group_ids_for_student(student_a.id) == []


async def test_pool_reuse_after_commit_sees_nothing_without_cast_error(
    db_env: str,
) -> None:
    """Раздел 5, пункт «пул»: одно соединение, контекст истёк — 0 строк."""
    async with postgres_schema(db_env):
        pass  # схема построена; ниже — отдельный движок с пулом на одно соединение

    single_connection_engine = create_engine(db_env, poolclass=StaticPool)
    try:
        session_factory = create_session_factory(single_connection_engine)
        institution = await _seed_institution(session_factory)

        uow = SqlAlchemyUnitOfWork(session_factory)
        async with uow as opened:
            scope = await opened.for_institution(institution.id)
            await scope.memberships.add(_new_membership(institution_id=institution.id))
            await opened.commit()

        # Тот же пул (``StaticPool`` — одно физическое соединение), но
        # контекст ``app.institution_id`` истёк вместе с транзакцией
        # коммита (ловушка A1) — ``NULLIF`` не даёт упасть на приведении
        # пустой строки к uuid, просто ноль строк.
        async with session_factory() as session:
            count = (
                await session.execute(text("SELECT count(*) FROM memberships"))
            ).scalar_one()
            assert count == 0
    finally:
        await single_connection_engine.dispose()


async def test_app_role_cannot_bypass_history_immutability(db_env: str) -> None:
    """Раздел 5, пункт «gamification_app»: TRUNCATE/DELETE/UPDATE и роль."""
    async with postgres_schema(db_env) as engine:
        async with engine.connect() as connection:
            role_row = (
                await connection.execute(
                    text(
                        "SELECT rolsuper OR rolbypassrls AS bypasses_rls "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
            assert role_row.bypasses_rls is False

            # pg_has_role(..., 'USAGE'), а не tableowner = current_user
            # (L3): ловит и членство в роли-владельце, не только прямое
            # совпадение.
            owned_tables = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' "
                        "AND pg_has_role(current_user, tableowner, 'USAGE')"
                    )
                )
            ).scalar_one()
            assert owned_tables == 0

        async with engine.begin() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(text("TRUNCATE currency_transactions"))
        async with engine.begin() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(text("DELETE FROM currency_transactions"))
        async with engine.begin() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(
                    text("UPDATE currency_transactions SET amount = amount")
                )
        async with engine.begin() as connection:
            with pytest.raises(DBAPIError):
                await connection.execute(
                    text(
                        "ALTER TABLE currency_transactions "
                        "DISABLE TRIGGER trg_currency_transactions_immutable"
                    )
                )


async def test_owner_truncate_is_rejected_by_trigger(
    db_env: str, db_owner_url: str
) -> None:
    """Раздел 5, пункт «владелец»: владельца не держит GRANT, держит триггер (У5)."""
    async with postgres_schema(db_env):
        owner_engine = create_engine(db_owner_url)
        try:
            async with owner_engine.begin() as connection:
                with pytest.raises(DBAPIError):
                    await connection.execute(text("TRUNCATE currency_transactions"))
        finally:
            await owner_engine.dispose()


async def test_user_memberships_lookup_sees_own_across_institutions_not_foreign(
    db_env: str,
) -> None:
    """Раздел 5, пункт «межарендные порты»: В1/X1, ``list_for_user``."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution_a = await _seed_institution(session_factory)
        institution_b = await _seed_institution(session_factory)
        user_id = uuid.uuid4()
        stranger_id = uuid.uuid4()

        async with session_factory() as session:
            await set_institution_context(session, institution_a.id)
            await SqlAlchemyInstitutionMemberships(session, institution_a.id).add(
                _new_membership(user_id=user_id, institution_id=institution_a.id)
            )
            await session.commit()

            await set_institution_context(session, institution_b.id)
            await SqlAlchemyInstitutionMemberships(session, institution_b.id).add(
                _new_membership(user_id=user_id, institution_id=institution_b.id)
            )
            await session.commit()

            await set_institution_context(session, institution_b.id)
            await SqlAlchemyInstitutionMemberships(session, institution_b.id).add(
                _new_membership(user_id=stranger_id, institution_id=institution_b.id)
            )
            await session.commit()

        async with session_factory() as session:
            # Без контекста учреждения — только своё, по app.user_id (X1).
            own = await SqlAlchemyUserMemberships(session).list_for_user(user_id)
            assert {m.institution_id for m in own} == {
                institution_a.id,
                institution_b.id,
            }
            # Порт возвращает «все членства пользователя во всех
            # учреждениях» (контракт ``UserMemberships.list_for_user``) —
            # членство соседнего пользователя в той же institution_b сюда
            # не должно попасть.
            assert {m.user_id for m in own} == {user_id}

            # Сырой SELECT без фильтра и без app.institution_id — чтобы
            # убедиться, что чужие строки отсекает сама политика RLS
            # (по app.user_id, выставленному list_for_user), а не
            # ``WHERE user_id = …`` в адаптере.
            raw_user_ids = (
                (await session.execute(text("SELECT user_id FROM memberships")))
                .scalars()
                .all()
            )
            assert set(raw_user_ids) == {user_id}
            assert stranger_id not in raw_user_ids

            # Тот же вызов сам выставляет app.user_id заново под другого
            # пользователя: по контракту это ``list_for_user(stranger_id)`` —
            # он должен увидеть ровно свои членства, а не членства
            # предыдущего пользователя в той же транзакции.
            foreign = await SqlAlchemyUserMemberships(session).list_for_user(
                stranger_id
            )
            assert {m.institution_id for m in foreign} == {institution_b.id}
            assert {m.user_id for m in foreign} == {stranger_id}


async def test_invitation_lookup_finds_by_token_not_by_foreign_token(
    db_env: str,
) -> None:
    """Раздел 5, пункт «межарендные порты»: В1/X1, ``get_for_accept``."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution = await _seed_institution(session_factory)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            await session.execute(
                text(
                    "INSERT INTO invitations "
                    "(id, institution_id, token, role, max_uses, uses_count, "
                    "created_by, created_at) "
                    "VALUES (:id, :institution_id, :token, 'student', 1, 0, "
                    ":created_by, now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "institution_id": str(institution.id),
                    "token": "real-token",
                    "created_by": str(uuid.uuid4()),
                },
            )
            await session.commit()

        async with session_factory() as session:
            found = await SqlAlchemyInvitationLookup(session).get_for_accept(
                "real-token"
            )
            assert found is not None
            assert found.institution_id == institution.id

            not_found = await SqlAlchemyInvitationLookup(session).get_for_accept(
                "someone-elses-token"
            )
            assert not_found is None


async def test_unit_of_work_rejects_second_institution_in_one_transaction(
    db_env: str,
) -> None:
    """Раздел 5: повторный ``for_institution`` с другим id — ``RuntimeError``."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        uow = SqlAlchemyUnitOfWork(session_factory)
        async with uow as opened:
            await opened.for_institution(uuid.uuid4())
            with pytest.raises(RuntimeError):
                await opened.for_institution(uuid.uuid4())
