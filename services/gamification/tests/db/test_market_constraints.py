"""Db-тесты гонок и ограничений маркета (план 07, Ч1, раздел 5).

Требуют поднятого docker-стека и обоих DSN — см. ``tests/db/test_rls.py``.
Политики RLS на ``privileges``/``purchases`` проверяет
``tests/db/test_rls.py`` (список ``RLS_TABLES``); здесь — только гонки и
ограничения, специфичные для маркета.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DBAPIError

from app.business.domain.entities import (
    CurrencyTransaction,
    Institution,
    Membership,
    Privilege,
    Purchase,
)
from app.business.domain.enums import (
    InstitutionKind,
    MembershipStatus,
    PurchaseStatus,
    TransactionKind,
    UserRole,
)
from app.business.domain.errors import (
    InsufficientBalanceError,
    OutOfStockError,
    PurchaseAlreadyResolvedError,
)
from app.repositories.database import create_session_factory
from app.repositories.models import CurrencyBalanceModel, CurrencyTransactionModel
from app.repositories.sql_alchemy import (
    SqlAlchemyCurrencyRepository,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
    SqlAlchemyMarketRepository,
)
from tests.contract.conftest import postgres_schema
from tests.db.conftest import set_institution_context


def _new_privilege(**overrides: object) -> Privilege:
    now = datetime.now(UTC)
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        title="Кофе",
        description=None,
        price=10,
        stock=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Privilege(**defaults)  # type: ignore[arg-type]


async def _seed_institution_and_student(session_factory):
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


async def _seed_balance(session_factory, institution, student, admin, amount):
    async with session_factory() as session:
        await set_institution_context(session, institution.id)
        repo = SqlAlchemyCurrencyRepository(session, institution.id)
        await repo.record(
            CurrencyTransaction(
                id=uuid.uuid4(),
                institution_id=institution.id,
                membership_id=student.id,
                kind=TransactionKind.MANUAL_ACCRUAL,
                amount=amount,
                comment=None,
                created_by_membership_id=admin.id,
                operation_id=uuid.uuid4(),
                reverses_id=None,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()


async def _seed_privilege(session_factory, institution, **overrides):
    async with session_factory() as session:
        await set_institution_context(session, institution.id)
        repo = SqlAlchemyMarketRepository(session, institution.id)
        privilege = _new_privilege(institution_id=institution.id, **overrides)
        await repo.add_privilege(privilege)
        await session.commit()
    return privilege


async def test_twenty_parallel_purchases_at_ten_with_balance_fifty_succeed_five_times(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_student(
            session_factory
        )
        await _seed_balance(session_factory, institution, student, admin, 50)
        privilege = await _seed_privilege(session_factory, institution, price=10)

        async def buy() -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyMarketRepository(session, institution.id)
                try:
                    await repo.purchase(
                        membership_id=student.id,
                        privilege_id=privilege.id,
                        expected_price=10,
                        operation_id=uuid.uuid4(),
                        created_at=datetime.now(UTC),
                    )
                    await session.commit()
                except InsufficientBalanceError as error:
                    return error
                return None

        results = await asyncio.gather(*(buy() for _ in range(20)))
        successes = [r for r in results if r is None]
        assert len(successes) == 5

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            balance = await SqlAlchemyCurrencyRepository(
                session, institution.id
            ).get_balance(student.id)
        assert balance == 0


async def test_ten_buyers_with_stock_three_succeed_three_times(db_env: str) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, _seed_student, admin = await _seed_institution_and_student(
            session_factory
        )
        privilege = await _seed_privilege(
            session_factory, institution, price=5, stock=3
        )

        students = []
        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            membership_repo = SqlAlchemyInstitutionMemberships(session, institution.id)
            for _ in range(10):
                student = Membership(
                    id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    institution_id=institution.id,
                    role=UserRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                    created_at=datetime.now(UTC),
                )
                await membership_repo.add(student)
                students.append(student)
            await session.commit()

        async def fund_and_buy(student: Membership) -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                currency_repo = SqlAlchemyCurrencyRepository(session, institution.id)
                await currency_repo.record(
                    CurrencyTransaction(
                        id=uuid.uuid4(),
                        institution_id=institution.id,
                        membership_id=student.id,
                        kind=TransactionKind.MANUAL_ACCRUAL,
                        amount=100,
                        comment=None,
                        created_by_membership_id=admin.id,
                        operation_id=uuid.uuid4(),
                        reverses_id=None,
                        created_at=datetime.now(UTC),
                    )
                )
                await session.commit()

            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                market_repo = SqlAlchemyMarketRepository(session, institution.id)
                try:
                    await market_repo.purchase(
                        membership_id=student.id,
                        privilege_id=privilege.id,
                        expected_price=5,
                        operation_id=uuid.uuid4(),
                        created_at=datetime.now(UTC),
                    )
                    await session.commit()
                except OutOfStockError as error:
                    return error
                return None

        results = await asyncio.gather(*(fund_and_buy(s) for s in students))
        successes = [r for r in results if r is None]
        assert len(successes) == 3

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            market_repo = SqlAlchemyMarketRepository(session, institution.id)
            fresh = await market_repo.get_privilege(privilege.id)
        assert fresh.stock == 0


async def test_parallel_fulfil_and_reject_only_one_applies(db_env: str) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_student(
            session_factory
        )
        await _seed_balance(session_factory, institution, student, admin, 50)
        privilege = await _seed_privilege(session_factory, institution, price=10)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            market_repo = SqlAlchemyMarketRepository(session, institution.id)
            purchase = await market_repo.purchase(
                membership_id=student.id,
                privilege_id=privilege.id,
                expected_price=10,
                operation_id=uuid.uuid4(),
                created_at=datetime.now(UTC),
            )
            await session.commit()

        async def fulfil() -> str:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyMarketRepository(session, institution.id)
                try:
                    result = await repo.resolve_fulfil(
                        purchase.id,
                        resolved_by_membership_id=admin.id,
                        now=datetime.now(UTC),
                    )
                    await session.commit()
                    return result.status.value
                except PurchaseAlreadyResolvedError:
                    return "conflict"

        async def reject() -> str:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyMarketRepository(session, institution.id)
                try:
                    result = await repo.resolve_reject(
                        purchase.id,
                        resolved_by_membership_id=admin.id,
                        now=datetime.now(UTC),
                        refund_operation_id=uuid.uuid4(),
                    )
                    await session.commit()
                    return result.status.value
                except PurchaseAlreadyResolvedError:
                    return "conflict"

        fulfil_result, reject_result = await asyncio.gather(fulfil(), reject())

        outcomes = {fulfil_result, reject_result}
        # Ровно одно решение применилось; второй участник либо получил тот
        # же исход (проиграл гонку, но перечитал совпавший статус), либо
        # явный конфликт.
        assert outcomes <= {"fulfilled", "rejected", "conflict"}
        assert not ({"fulfilled", "rejected"} <= outcomes)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            final = await SqlAlchemyMarketRepository(
                session, institution.id
            ).get_purchase(purchase.id)
        assert final.status in (PurchaseStatus.FULFILLED, PurchaseStatus.REJECTED)


async def test_parallel_reversal_and_purchase_keep_balance_non_negative(
    db_env: str,
) -> None:
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_student(
            session_factory
        )
        privilege = await _seed_privilege(session_factory, institution, price=40)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            currency_repo = SqlAlchemyCurrencyRepository(session, institution.id)
            accrual = CurrencyTransaction(
                id=uuid.uuid4(),
                institution_id=institution.id,
                membership_id=student.id,
                kind=TransactionKind.MANUAL_ACCRUAL,
                amount=40,
                comment=None,
                created_by_membership_id=admin.id,
                operation_id=uuid.uuid4(),
                reverses_id=None,
                created_at=datetime.now(UTC),
            )
            await currency_repo.record(accrual)
            await session.commit()

        async def purchase() -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyMarketRepository(session, institution.id)
                try:
                    await repo.purchase(
                        membership_id=student.id,
                        privilege_id=privilege.id,
                        expected_price=40,
                        operation_id=uuid.uuid4(),
                        created_at=datetime.now(UTC),
                    )
                    await session.commit()
                except InsufficientBalanceError as error:
                    return error
                return None

        async def reverse() -> Exception | None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                repo = SqlAlchemyCurrencyRepository(session, institution.id)
                try:
                    await repo.record(
                        CurrencyTransaction(
                            id=uuid.uuid4(),
                            institution_id=institution.id,
                            membership_id=student.id,
                            kind=TransactionKind.REVERSAL,
                            amount=-40,
                            comment=None,
                            created_by_membership_id=admin.id,
                            operation_id=uuid.uuid4(),
                            reverses_id=accrual.id,
                            created_at=datetime.now(UTC),
                        )
                    )
                    await session.commit()
                except InsufficientBalanceError as error:
                    return error
                return None

        await asyncio.gather(purchase(), reverse())

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            balance = await SqlAlchemyCurrencyRepository(
                session, institution.id
            ).get_balance(student.id)
        assert balance >= 0


async def test_purchase_and_reject_do_not_deadlock(db_env: str) -> None:
    """Риск 1 плана 07: порядок блокировок «позиция → баланс» обязан
    совпадать в ``purchase()`` и ``resolve_reject()``.

    Пара на каждого ученика: ``T1`` покупает вторую единицу позиции ``P``
    (блокирует ``P``, затем баланс), ``T2`` отклоняет уже существующую
    ``pending``-покупку того же ученика по той же ``P`` (при старом
    порядке — блокирует баланс, затем ``P``). Встречный порядок при живой
    гонке в Postgres даёт ``40P01``; несколько независимых пар запускаются
    одновременно, чтобы увеличить шанс совпасть по времени.

    Честно: на этой машине (Windows, гранулярность таймера ``asyncio.sleep``
    заметно грубее миллисекунды, ``NullPool`` — новое соединение на каждую
    сессию) вероятностная гонка через ``asyncio.gather`` ни разу не поймала
    ``40P01`` даже на старом порядке при разумном ``N`` — см. отчёт: там же
    отдельная проверка двумя настоящими соединениями с ручной синхронизацией
    точек блокировки (не в составе тестов, диагностический скрипт),
    подтвердившая, что Postgres действительно детектирует дедлок для точно
    такого же паттерна ``UPDATE privileges`` / ``UPDATE currency_balances``
    во встречном порядке. Тест остаётся: он ловит регресс, если гонка
    когда-нибудь совпадёт по времени, и проверяет инварианты согласованности
    независимо от того, совпала она или нет.
    """
    pairs_count = 20
    price = 10
    seed_balance = 30  # 30 - price(10) на pending-покупку = 20 к моменту гонки

    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, _unused_student, admin = await _seed_institution_and_student(
            session_factory
        )

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            membership_repo = SqlAlchemyInstitutionMemberships(session, institution.id)
            students = []
            for _ in range(pairs_count):
                student = Membership(
                    id=uuid.uuid4(),
                    user_id=uuid.uuid4(),
                    institution_id=institution.id,
                    role=UserRole.STUDENT,
                    status=MembershipStatus.ACTIVE,
                    created_at=datetime.now(UTC),
                )
                await membership_repo.add(student)
                students.append(student)
            await session.commit()

        pairs: list[tuple[Membership, Privilege, Purchase]] = []
        for student in students:
            await _seed_balance(
                session_factory, institution, student, admin, seed_balance
            )
            privilege = await _seed_privilege(session_factory, institution, price=price)
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                market_repo = SqlAlchemyMarketRepository(session, institution.id)
                pending_purchase = await market_repo.purchase(
                    membership_id=student.id,
                    privilege_id=privilege.id,
                    expected_price=price,
                    operation_id=uuid.uuid4(),
                    created_at=datetime.now(UTC),
                )
                await session.commit()
            pairs.append((student, privilege, pending_purchase))

        async def buy_more(student: Membership, privilege: Privilege) -> None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                market_repo = SqlAlchemyMarketRepository(session, institution.id)
                await market_repo.purchase(
                    membership_id=student.id,
                    privilege_id=privilege.id,
                    expected_price=price,
                    operation_id=uuid.uuid4(),
                    created_at=datetime.now(UTC),
                )
                await session.commit()

        async def reject_pending(purchase: Purchase) -> None:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                market_repo = SqlAlchemyMarketRepository(session, institution.id)
                await market_repo.resolve_reject(
                    purchase.id,
                    resolved_by_membership_id=admin.id,
                    now=datetime.now(UTC),
                    refund_operation_id=uuid.uuid4(),
                )
                await session.commit()

        tasks = []
        for student, privilege, pending_purchase in pairs:
            tasks.append(buy_more(student, privilege))
            tasks.append(reject_pending(pending_purchase))

        # Ни ``40P01``, ни любое другое непредвиденное исключение проходить
        # не должны — при первом же ``DBAPIError``/ином сбое ``gather`` его
        # пробрасывает, и тест падает.
        await asyncio.gather(*tasks)

        for student, privilege, _pending_purchase in pairs:
            async with session_factory() as session:
                await set_institution_context(session, institution.id)
                balance = await SqlAlchemyCurrencyRepository(
                    session, institution.id
                ).get_balance(student.id)
                fresh_privilege = await SqlAlchemyMarketRepository(
                    session, institution.id
                ).get_privilege(privilege.id)
                transactions = await session.execute(
                    select(func.sum(CurrencyTransactionModel.amount)).where(
                        CurrencyTransactionModel.institution_id == institution.id,
                        CurrencyTransactionModel.membership_id == student.id,
                    )
                )
                history_sum = transactions.scalar_one()

            # Отклонённая исходная покупка вернула деньги, вторая покупка
            # их списала обратно — итог совпадает с состоянием после
            # единственной успешной покупки (порядок двух конкурентных
            # операций коммутативен для этого сценария).
            assert balance == seed_balance - price
            assert balance >= 0
            assert balance == history_sum
            # Позиция без лимита (``stock=None``, L2) не меняется number-ом.
            assert fresh_privilege.stock is None


async def test_direct_update_of_balance_below_zero_fails_check(db_env: str) -> None:
    """П3: CHECK (balance >= 0) — второй рубеж поверх условного UPDATE.

    Под ролью приложения (``gamification_app``): у неё есть ``UPDATE`` на
    ``currency_balances`` (У3 плана 07a), это именно та роль, которой
    разрешена операция и которую должен ловить CHECK, а не отказ в правах.
    """
    async with postgres_schema(db_env) as engine:
        session_factory = create_session_factory(engine)
        institution, student, admin = await _seed_institution_and_student(
            session_factory
        )
        await _seed_balance(session_factory, institution, student, admin, 10)

        async with session_factory() as session:
            await set_institution_context(session, institution.id)
            with pytest.raises(DBAPIError):
                await session.execute(
                    update(CurrencyBalanceModel)
                    .where(CurrencyBalanceModel.membership_id == student.id)
                    .values(balance=-1)
                )
                await session.commit()
            await session.rollback()
