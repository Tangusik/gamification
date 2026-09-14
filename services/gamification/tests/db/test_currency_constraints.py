"""Db-тесты ограничений схемы валюты (Ч1 плана 06): гонка начислений,
гонка повтора ``operation_id``, неизменяемость истории (У4).

Требуют поднятого docker-стека и ``GAMIFICATION_TEST_DATABASE_URL`` — без
переменной пропускаются ``tests/db/conftest.py``. Триггер проверяется
отдельно от ``test_migration_matches_models.py`` — ``compare_metadata``
его не видит (раздел 5 плана).
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError

from app.business.domain.entities import CurrencyTransaction, Institution, Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import (
    OperationIdConflictError,
    TransactionAlreadyReversedError,
)
from app.repositories.database import create_engine, create_session_factory
from app.repositories.models import CurrencyTransactionModel
from app.repositories.sql_alchemy import (
    SqlAlchemyCurrencyRepository,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
)
from tests.contract.conftest import postgres_schema
from tests.db.conftest import set_institution_context

# SQLSTATE безымянного ``RAISE EXCEPTION`` без явного кода (``0003_currency.py``)
# — по умолчанию PostgreSQL присваивает такому исключению ``P0001``.
_APPEND_ONLY_TRIGGER_SQLSTATE = "P0001"


def _is_append_only_violation(error: DBAPIError) -> bool:
    """Отличить срабатывание триггера неизменяемости от отказа в правах.

    У ``gamification_app`` на ``currency_transactions`` нет ``UPDATE``/
    ``DELETE`` вовсе (У3) — такой отказ ловит ``permission denied`` в
    ``test_rls.py`` (``test_app_role_cannot_bypass_history_immutability``)
    и не должен приниматься здесь за проверку триггера: широкий
    ``except DBAPIError`` этого не различает.
    """
    sqlstate = getattr(error.orig, "sqlstate", None)
    message = str(error.orig)
    return sqlstate == _APPEND_ONLY_TRIGGER_SQLSTATE and "append-only" in message


def _new_transaction(**overrides: object) -> CurrencyTransaction:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        kind="manual_accrual",
        amount=10,
        comment=None,
        created_by_membership_id=uuid.uuid4(),
        operation_id=uuid.uuid4(),
        reverses_id=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return CurrencyTransaction(**defaults)  # type: ignore[arg-type]


async def _seed_institution_and_members(session_factory):
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

        # RLS-таблицы (У4): контекст выставляется заново после commit —
        # он локален транзакции и не переживает её конец (ловушка A1,
        # риск 2 плана 07a).
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
        admin = Membership(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            institution_id=institution.id,
            role=UserRole.INSTITUTION_ADMIN,
            status=MembershipStatus.ACTIVE,
            created_at=datetime.now(UTC),
        )
        await membership_repo.add(student)
        await membership_repo.add(admin)
        await session.commit()
    return institution, student, admin


async def test_twenty_parallel_accruals_balance_equals_history_sum(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_members(
            session_factory
        )

        async def accrue(amount: int) -> None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyCurrencyRepository(session, institution.id)
                await repo.record(
                    _new_transaction(
                        institution_id=institution.id,
                        membership_id=student.id,
                        created_by_membership_id=admin.id,
                        amount=amount,
                    )
                )
                await session.commit()

        amounts = list(range(1, 21))
        await asyncio.gather(*(accrue(amount) for amount in amounts))

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            repo = SqlAlchemyCurrencyRepository(session, institution.id)
            balance = await repo.get_balance(student.id)
            history = await repo.list_transactions(student.id, limit=50)

        assert balance == sum(amounts)
        assert sum(tx.amount for tx in history) == balance
        assert len(history) == len(amounts)


async def test_parallel_repeat_of_operation_id_creates_one_record(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_members(
            session_factory
        )
        operation_id = uuid.uuid4()

        async def accrue() -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyCurrencyRepository(session, institution.id)
                try:
                    await repo.record(
                        _new_transaction(
                            institution_id=institution.id,
                            membership_id=student.id,
                            created_by_membership_id=admin.id,
                            amount=15,
                            operation_id=operation_id,
                        )
                    )
                    await session.commit()
                except OperationIdConflictError as error:
                    return error
                return None

        results = await asyncio.gather(accrue(), accrue())

        successes = [result for result in results if result is None]
        failures = [result for result in results if result is not None]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], OperationIdConflictError)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            repo = SqlAlchemyCurrencyRepository(session, institution.id)
            history = await repo.list_transactions(student.id, limit=50)
        assert len(history) == 1


async def test_parallel_reversal_race_yields_transaction_already_reversed(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_members(
            session_factory
        )
        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            repo = SqlAlchemyCurrencyRepository(session, institution.id)
            original = _new_transaction(
                institution_id=institution.id,
                membership_id=student.id,
                created_by_membership_id=admin.id,
                amount=40,
            )
            await repo.record(original)
            await session.commit()

        async def reverse(operation_id: uuid.UUID) -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyCurrencyRepository(session, institution.id)
                try:
                    await repo.record(
                        _new_transaction(
                            institution_id=institution.id,
                            membership_id=student.id,
                            kind="reversal",
                            amount=-40,
                            created_by_membership_id=admin.id,
                            reverses_id=original.id,
                            operation_id=operation_id,
                        )
                    )
                    await session.commit()
                except (
                    OperationIdConflictError,
                    TransactionAlreadyReversedError,
                ) as error:
                    return error
                return None

        results = await asyncio.gather(reverse(uuid.uuid4()), reverse(uuid.uuid4()))

        successes = [result for result in results if result is None]
        failures = [result for result in results if result is not None]
        assert len(successes) == 1
        assert len(failures) == 1
        # Проигравший пришёл с другим operation_id (риск гонки —
        # UNIQUE(reverses_id) отдаёт TRANSACTION_ALREADY_REVERSED, не
        # OPERATION_ID_CONFLICT).
        assert isinstance(failures[0], TransactionAlreadyReversedError)


async def test_update_on_currency_transactions_is_rejected_by_trigger(
    db_env: str, db_owner_url: str
) -> None:
    """Триггер, а не отказ в правах: ``gamification_app`` не имеет
    ``UPDATE`` на ``currency_transactions`` вовсе (У3), и под ней
    ``permission denied`` наступил бы раньше, чем сработал бы триггер —
    это отдельно проверяет ``test_app_role_cannot_bypass_history_immutability``
    в ``test_rls.py``. Здесь нужен путь, где ``GRANT`` есть (роль-владелец),
    чтобы дойти до самого триггера.
    """
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_members(
            session_factory
        )
        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            repo = SqlAlchemyCurrencyRepository(session, institution.id)
            transaction = _new_transaction(
                institution_id=institution.id,
                membership_id=student.id,
                created_by_membership_id=admin.id,
            )
            await repo.record(transaction)
            await session.commit()

        owner_engine = create_engine(db_owner_url)
        try:
            owner_session_factory = create_session_factory(owner_engine)
            async with owner_session_factory() as owner_session:
                # FORCE действует и на владельца таблиц — без контекста
                # строка была бы не видна политике (раздел 3 плана 07a,
                # доработка Ч2, пункт 2).
                await set_institution_context(owner_session, institution.id)
                with pytest.raises(DBAPIError) as excinfo:
                    await owner_session.execute(
                        update(CurrencyTransactionModel)
                        .where(CurrencyTransactionModel.id == transaction.id)
                        .values(amount=999)
                    )
                    await owner_session.commit()
                assert _is_append_only_violation(excinfo.value)
                await owner_session.rollback()
        finally:
            await owner_engine.dispose()


async def test_delete_on_currency_transactions_is_rejected_by_trigger(
    db_env: str, db_owner_url: str
) -> None:
    """:see: комментарий в тесте UPDATE выше — то же самое для ``DELETE``."""
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_members(
            session_factory
        )
        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            repo = SqlAlchemyCurrencyRepository(session, institution.id)
            transaction = _new_transaction(
                institution_id=institution.id,
                membership_id=student.id,
                created_by_membership_id=admin.id,
            )
            await repo.record(transaction)
            await session.commit()

        owner_engine = create_engine(db_owner_url)
        try:
            owner_session_factory = create_session_factory(owner_engine)
            async with owner_session_factory() as owner_session:
                await set_institution_context(owner_session, institution.id)
                with pytest.raises(DBAPIError) as excinfo:
                    await owner_session.execute(
                        CurrencyTransactionModel.__table__.delete().where(
                            CurrencyTransactionModel.id == transaction.id
                        )
                    )
                    await owner_session.commit()
                assert _is_append_only_violation(excinfo.value)
                await owner_session.rollback()
        finally:
            await owner_engine.dispose()

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            statement = select(CurrencyTransactionModel).where(
                CurrencyTransactionModel.id == transaction.id
            )
            result = await session.execute(statement)
            assert result.scalar_one_or_none() is not None
