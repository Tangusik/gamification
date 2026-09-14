"""Контрактные тесты репозитория валюты: обе реализации (раздел 7, план 06)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.entities import CurrencyTransaction, Institution, Membership
from app.business.domain.enums import (
    InstitutionKind,
    MembershipStatus,
    TransactionKind,
    UserRole,
)
from app.business.domain.errors import (
    MemberNotFoundError,
    OperationIdConflictError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
)


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


def _new_transaction(**overrides: object) -> CurrencyTransaction:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        membership_id=uuid.uuid4(),
        kind=TransactionKind.MANUAL_ACCRUAL,
        amount=50,
        comment=None,
        created_by_membership_id=uuid.uuid4(),
        operation_id=uuid.uuid4(),
        reverses_id=None,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return CurrencyTransaction(**defaults)  # type: ignore[arg-type]


async def _seed_institution(institution_repo) -> uuid.UUID:
    institution = Institution(
        id=uuid.uuid4(),
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    await institution_repo.add(institution)
    return institution.id


@pytest.fixture(params=["in_memory", pytest.param("postgres", marks=pytest.mark.db)])
async def currency_repos(request: pytest.FixtureRequest):
    """``(institution_repo, membership_repo_for, currency_repo_for)`` (H1).

    Обе фабрики асинхронны в обоих вариантах: под ``[postgres]`` они
    выставляют ``app.institution_id`` перед тем, как отдать репозиторий
    (У3-У5 плана 07a) — без этого ``FORCE ROW LEVEL SECURITY`` даёт 0
    строк на чтении ``currency_balances``/``currency_transactions`` и
    падение ``WITH CHECK`` на записи.
    """
    if request.param == "in_memory":
        from app.repositories.in_memory import (
            InMemoryCurrencyRepository,
            InMemoryInstitutionMemberships,
            InMemoryInstitutionRepository,
            InMemoryStore,
        )

        store = InMemoryStore()
        institution_repo = InMemoryInstitutionRepository(store)

        async def membership_repo_for(institution_id):
            return InMemoryInstitutionMemberships(store, institution_id)

        async def currency_repo_for(institution_id):
            return InMemoryCurrencyRepository(store, institution_id)

        yield institution_repo, membership_repo_for, currency_repo_for
        return

    from app.repositories.database import create_session_factory
    from app.repositories.sql_alchemy import (
        SqlAlchemyCurrencyRepository,
        SqlAlchemyInstitutionMemberships,
        SqlAlchemyInstitutionRepository,
    )
    from tests.contract.conftest import postgres_schema, require_test_database_url
    from tests.db.conftest import set_institution_context

    async with postgres_schema(require_test_database_url()) as engine:
        async with create_session_factory(engine)() as session:
            institution_repo = SqlAlchemyInstitutionRepository(session)

            async def membership_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyInstitutionMemberships(session, institution_id)

            async def currency_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyCurrencyRepository(session, institution_id)

            yield institution_repo, membership_repo_for, currency_repo_for


async def _seed_membership(
    membership_repo_for, institution_id: uuid.UUID, **overrides: object
) -> Membership:
    membership = _new_membership(institution_id=institution_id, **overrides)
    await (await membership_repo_for(institution_id)).add(membership)
    return membership


async def test_record_then_get_returns_the_transaction(currency_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    teacher = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_id)
    transaction = _new_transaction(
        institution_id=institution_id,
        membership_id=student.id,
        created_by_membership_id=teacher.id,
    )

    await currency_repo.record(transaction)
    fetched = await currency_repo.get(transaction.id)

    assert fetched is not None
    assert fetched.amount == transaction.amount
    assert fetched.kind is TransactionKind.MANUAL_ACCRUAL


async def test_record_upserts_balance(currency_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    teacher = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_id)
    await currency_repo.record(
        _new_transaction(
            institution_id=institution_id,
            membership_id=student.id,
            created_by_membership_id=teacher.id,
            amount=30,
        )
    )
    await currency_repo.record(
        _new_transaction(
            institution_id=institution_id,
            membership_id=student.id,
            created_by_membership_id=teacher.id,
            amount=20,
        )
    )

    assert await currency_repo.get_balance(student.id) == 50


async def test_get_balance_is_zero_without_a_row(currency_repos) -> None:
    institution_repo, _, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)

    assert (
        await (await currency_repo_for(institution_id)).get_balance(uuid.uuid4()) == 0
    )


async def test_list_balances_defaults_missing_to_zero(currency_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student_with_balance = await _seed_membership(membership_repo_for, institution_id)
    student_without_balance = await _seed_membership(
        membership_repo_for, institution_id
    )
    teacher = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_id)
    await currency_repo.record(
        _new_transaction(
            institution_id=institution_id,
            membership_id=student_with_balance.id,
            created_by_membership_id=teacher.id,
            amount=42,
        )
    )

    balances = await currency_repo.list_balances(
        [student_with_balance.id, student_without_balance.id]
    )

    assert balances == {student_with_balance.id: 42, student_without_balance.id: 0}


async def test_operation_id_is_unique_within_institution(currency_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    teacher = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_id)
    operation_id = uuid.uuid4()
    await currency_repo.record(
        _new_transaction(
            institution_id=institution_id,
            membership_id=student.id,
            created_by_membership_id=teacher.id,
            operation_id=operation_id,
        )
    )

    with pytest.raises(OperationIdConflictError):
        await currency_repo.record(
            _new_transaction(
                institution_id=institution_id,
                membership_id=student.id,
                created_by_membership_id=teacher.id,
                operation_id=operation_id,
            )
        )


async def test_get_by_operation_id_returns_none_for_other_institution(
    currency_repos,
) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_a = await _seed_membership(membership_repo_for, institution_a)
    teacher_a = await _seed_membership(
        membership_repo_for, institution_a, role=UserRole.TEACHER
    )
    operation_id = uuid.uuid4()
    await (await currency_repo_for(institution_a)).record(
        _new_transaction(
            institution_id=institution_a,
            membership_id=student_a.id,
            created_by_membership_id=teacher_a.id,
            operation_id=operation_id,
        )
    )

    assert (
        await (await currency_repo_for(institution_b)).get_by_operation_id(operation_id)
        is None
    )


async def test_reverses_id_is_unique(currency_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    admin = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.INSTITUTION_ADMIN
    )
    currency_repo = await currency_repo_for(institution_id)
    original = _new_transaction(
        institution_id=institution_id,
        membership_id=student.id,
        created_by_membership_id=admin.id,
        amount=40,
    )
    await currency_repo.record(original)
    await currency_repo.record(
        _new_transaction(
            institution_id=institution_id,
            membership_id=student.id,
            kind=TransactionKind.REVERSAL,
            amount=-40,
            created_by_membership_id=admin.id,
            reverses_id=original.id,
        )
    )

    with pytest.raises(TransactionAlreadyReversedError):
        await currency_repo.record(
            _new_transaction(
                institution_id=institution_id,
                membership_id=student.id,
                kind=TransactionKind.REVERSAL,
                amount=-40,
                created_by_membership_id=admin.id,
                reverses_id=original.id,
            )
        )


async def test_list_transactions_orders_newest_first_and_respects_limit(
    currency_repos,
) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    teacher = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_id)
    base_time = datetime.now(UTC)
    for index in range(3):
        await currency_repo.record(
            _new_transaction(
                institution_id=institution_id,
                membership_id=student.id,
                created_by_membership_id=teacher.id,
                amount=index + 1,
                created_at=base_time.replace(microsecond=index * 1000),
            )
        )

    transactions = await currency_repo.list_transactions(student.id, limit=2)

    assert [tx.amount for tx in transactions] == [3, 2]


async def test_record_rejects_membership_from_another_institution(
    currency_repos,
) -> None:
    """H1/L2: ``membership_id`` цели из чужого учреждения не проходит,
    история и баланс не меняются.
    """
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    foreign_student = await _seed_membership(membership_repo_for, institution_b)
    teacher_a = await _seed_membership(
        membership_repo_for, institution_a, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_a)
    transaction = _new_transaction(
        institution_id=institution_a,
        membership_id=foreign_student.id,
        created_by_membership_id=teacher_a.id,
    )

    with pytest.raises(MemberNotFoundError):
        await currency_repo.record(transaction)

    assert await currency_repo.get(transaction.id) is None
    assert await currency_repo.get_balance(foreign_student.id) == 0


async def test_record_rejects_author_from_another_institution(
    currency_repos,
) -> None:
    """H1/L2: ``created_by_membership_id`` из чужого учреждения не
    проходит, история и баланс не меняются.
    """
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_a = await _seed_membership(membership_repo_for, institution_a)
    foreign_teacher = await _seed_membership(
        membership_repo_for, institution_b, role=UserRole.TEACHER
    )
    currency_repo = await currency_repo_for(institution_a)
    transaction = _new_transaction(
        institution_id=institution_a,
        membership_id=student_a.id,
        created_by_membership_id=foreign_teacher.id,
    )

    with pytest.raises(MemberNotFoundError):
        await currency_repo.record(transaction)

    assert await currency_repo.get(transaction.id) is None
    assert await currency_repo.get_balance(student_a.id) == 0


async def test_record_rejects_reversal_of_transaction_from_another_institution(
    currency_repos,
) -> None:
    """H1/L2: ``reverses_id`` указывает на запись чужого учреждения."""
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_a = await _seed_membership(membership_repo_for, institution_a)
    admin_a = await _seed_membership(
        membership_repo_for, institution_a, role=UserRole.INSTITUTION_ADMIN
    )
    student_b = await _seed_membership(membership_repo_for, institution_b)
    admin_b = await _seed_membership(
        membership_repo_for, institution_b, role=UserRole.INSTITUTION_ADMIN
    )
    original_b = _new_transaction(
        institution_id=institution_b,
        membership_id=student_b.id,
        created_by_membership_id=admin_b.id,
        amount=40,
    )
    await (await currency_repo_for(institution_b)).record(original_b)

    currency_repo_a = await currency_repo_for(institution_a)
    reversal = _new_transaction(
        institution_id=institution_a,
        membership_id=student_a.id,
        kind=TransactionKind.REVERSAL,
        amount=-40,
        created_by_membership_id=admin_a.id,
        reverses_id=original_b.id,
    )

    with pytest.raises(TransactionNotFoundError):
        await currency_repo_a.record(reversal)

    assert await currency_repo_a.get(reversal.id) is None
    assert await currency_repo_a.get_balance(student_a.id) == 0


async def test_get_balance_of_membership_from_another_institution_is_zero(
    currency_repos,
) -> None:
    """L3: баланс чужого членства не виден ни в ``get_balance``, ни в
    ``list_balances``.
    """
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_b = await _seed_membership(membership_repo_for, institution_b)
    teacher_b = await _seed_membership(
        membership_repo_for, institution_b, role=UserRole.TEACHER
    )
    await (await currency_repo_for(institution_b)).record(
        _new_transaction(
            institution_id=institution_b,
            membership_id=student_b.id,
            created_by_membership_id=teacher_b.id,
            amount=99,
        )
    )

    currency_repo_a = await currency_repo_for(institution_a)
    assert await currency_repo_a.get_balance(student_b.id) == 0
    assert await currency_repo_a.list_balances([student_b.id]) == {student_b.id: 0}


async def test_list_transactions_does_not_see_other_institution(
    currency_repos,
) -> None:
    institution_repo, membership_repo_for, currency_repo_for = currency_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_a = await _seed_membership(membership_repo_for, institution_a)
    teacher_a = await _seed_membership(
        membership_repo_for, institution_a, role=UserRole.TEACHER
    )
    await (await currency_repo_for(institution_a)).record(
        _new_transaction(
            institution_id=institution_a,
            membership_id=student_a.id,
            created_by_membership_id=teacher_a.id,
        )
    )

    transactions = await (await currency_repo_for(institution_b)).list_transactions(
        student_a.id, limit=50
    )

    assert transactions == []
