"""Контрактные тесты репозитория маркета: обе реализации (H1, план 07)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.entities import Institution, Membership, Privilege
from app.business.domain.enums import (
    InstitutionKind,
    MembershipStatus,
    PurchaseStatus,
    UserRole,
)
from app.business.domain.errors import (
    InsufficientBalanceError,
    OperationIdConflictError,
    OutOfStockError,
    PriceChangedError,
    PrivilegeNotFoundError,
    PurchaseAlreadyResolvedError,
    PurchaseNotFoundError,
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


def _new_privilege(**overrides: object) -> Privilege:
    now = datetime.now(UTC)
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        title="Кофе",
        description=None,
        price=30,
        stock=None,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    return Privilege(**defaults)  # type: ignore[arg-type]


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
async def market_repos(request: pytest.FixtureRequest):
    """``(institution_repo, membership_repo_for, currency_repo_for, market_repo_for)``.

    Четыре фабрики, как в ``test_currency_repository.py``, плюс маркет.
    """
    if request.param == "in_memory":
        from app.repositories.in_memory import (
            InMemoryCurrencyRepository,
            InMemoryInstitutionMemberships,
            InMemoryInstitutionRepository,
            InMemoryMarketRepository,
            InMemoryStore,
        )

        store = InMemoryStore()
        institution_repo = InMemoryInstitutionRepository(store)

        async def membership_repo_for(institution_id):
            return InMemoryInstitutionMemberships(store, institution_id)

        async def currency_repo_for(institution_id):
            return InMemoryCurrencyRepository(store, institution_id)

        async def market_repo_for(institution_id):
            return InMemoryMarketRepository(store, institution_id)

        yield institution_repo, membership_repo_for, currency_repo_for, market_repo_for
        return

    from app.repositories.database import create_session_factory
    from app.repositories.sql_alchemy import (
        SqlAlchemyCurrencyRepository,
        SqlAlchemyInstitutionMemberships,
        SqlAlchemyInstitutionRepository,
        SqlAlchemyMarketRepository,
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

            async def market_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyMarketRepository(session, institution_id)

            yield (
                institution_repo,
                membership_repo_for,
                currency_repo_for,
                market_repo_for,
            )


async def _seed_membership(
    membership_repo_for, institution_id: uuid.UUID, **overrides: object
) -> Membership:
    membership = _new_membership(institution_id=institution_id, **overrides)
    await (await membership_repo_for(institution_id)).add(membership)
    return membership


async def _seed_balance(currency_repo_for, institution_id, membership_id, amount):
    from app.business.domain.entities import CurrencyTransaction
    from app.business.domain.enums import TransactionKind

    repo = await currency_repo_for(institution_id)
    await repo.record(
        CurrencyTransaction(
            id=uuid.uuid4(),
            institution_id=institution_id,
            membership_id=membership_id,
            kind=TransactionKind.MANUAL_ACCRUAL,
            amount=amount,
            comment=None,
            created_by_membership_id=membership_id,
            operation_id=uuid.uuid4(),
            reverses_id=None,
            created_at=datetime.now(UTC),
        )
    )


async def test_add_privilege_then_get_returns_it(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id)

    await market_repo.add_privilege(privilege)
    fetched = await market_repo.get_privilege(privilege.id)

    assert fetched is not None
    assert fetched.title == "Кофе"
    assert fetched.stock is None


async def test_list_privileges_active_only(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    market_repo = await market_repo_for(institution_id)
    active = _new_privilege(institution_id=institution_id, is_active=True)
    hidden = _new_privilege(institution_id=institution_id, is_active=False)
    await market_repo.add_privilege(active)
    await market_repo.add_privilege(hidden)

    only_active = await market_repo.list_privileges(active_only=True)
    everything = await market_repo.list_privileges(active_only=False)

    assert {p.id for p in only_active} == {active.id}
    assert {p.id for p in everything} == {active.id, hidden.id}


async def test_update_privilege_returns_none_for_foreign_institution(
    market_repos,
) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    market_repo_a = await market_repo_for(institution_a)
    privilege = _new_privilege(institution_id=institution_a)
    await market_repo_a.add_privilege(privilege)

    market_repo_b = await market_repo_for(institution_b)
    result = await market_repo_b.update_privilege(privilege)

    assert result is None


async def test_purchase_debits_balance_and_decrements_stock(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 100)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=30, stock=2)
    await market_repo.add_privilege(privilege)

    purchase = await market_repo.purchase(
        membership_id=student.id,
        privilege_id=privilege.id,
        expected_price=30,
        operation_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )

    assert purchase.status is PurchaseStatus.PENDING
    assert purchase.price == 30
    updated_privilege = await market_repo.get_privilege(privilege.id)
    assert updated_privilege.stock == 1
    balance = await (await currency_repo_for(institution_id)).get_balance(student.id)
    assert balance == 70


async def test_purchase_operation_id_is_unique_within_institution(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 100)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=10)
    await market_repo.add_privilege(privilege)
    operation_id = uuid.uuid4()
    await market_repo.purchase(
        membership_id=student.id,
        privilege_id=privilege.id,
        expected_price=10,
        operation_id=operation_id,
        created_at=datetime.now(UTC),
    )

    with pytest.raises(OperationIdConflictError):
        await market_repo.purchase(
            membership_id=student.id,
            privilege_id=privilege.id,
            expected_price=10,
            operation_id=operation_id,
            created_at=datetime.now(UTC),
        )


async def test_purchase_price_mismatch_is_rejected(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 100)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=30)
    await market_repo.add_privilege(privilege)

    with pytest.raises(PriceChangedError):
        await market_repo.purchase(
            membership_id=student.id,
            privilege_id=privilege.id,
            expected_price=20,
            operation_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )


async def test_purchase_out_of_stock_is_rejected(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 100)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=10, stock=0)
    await market_repo.add_privilege(privilege)

    with pytest.raises(OutOfStockError):
        await market_repo.purchase(
            membership_id=student.id,
            privilege_id=privilege.id,
            expected_price=10,
            operation_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )


async def test_purchase_hidden_privilege_is_not_found(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 100)
    market_repo = await market_repo_for(institution_id)
    hidden = _new_privilege(institution_id=institution_id, price=10, is_active=False)
    await market_repo.add_privilege(hidden)

    with pytest.raises(PrivilegeNotFoundError):
        await market_repo.purchase(
            membership_id=student.id,
            privilege_id=hidden.id,
            expected_price=10,
            operation_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )


async def test_purchase_insufficient_balance_is_rejected(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    await _seed_balance(currency_repo_for, institution_id, student.id, 5)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=10)
    await market_repo.add_privilege(privilege)

    with pytest.raises(InsufficientBalanceError):
        await market_repo.purchase(
            membership_id=student.id,
            privilege_id=privilege.id,
            expected_price=10,
            operation_id=uuid.uuid4(),
            created_at=datetime.now(UTC),
        )

    balance = await (await currency_repo_for(institution_id)).get_balance(student.id)
    assert balance == 5
    fresh_privilege = await market_repo.get_privilege(privilege.id)
    assert fresh_privilege.price == 10


async def test_resolve_fulfil_and_reject_are_idempotent(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    admin = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.INSTITUTION_ADMIN
    )
    await _seed_balance(currency_repo_for, institution_id, student.id, 50)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=20, stock=1)
    await market_repo.add_privilege(privilege)
    purchase = await market_repo.purchase(
        membership_id=student.id,
        privilege_id=privilege.id,
        expected_price=20,
        operation_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )

    fulfilled = await market_repo.resolve_fulfil(
        purchase.id, resolved_by_membership_id=admin.id, now=datetime.now(UTC)
    )
    again = await market_repo.resolve_fulfil(
        purchase.id, resolved_by_membership_id=admin.id, now=datetime.now(UTC)
    )
    assert fulfilled.status is PurchaseStatus.FULFILLED
    assert again.status is PurchaseStatus.FULFILLED

    with pytest.raises(PurchaseAlreadyResolvedError):
        await market_repo.resolve_reject(
            purchase.id,
            resolved_by_membership_id=admin.id,
            now=datetime.now(UTC),
            refund_operation_id=uuid.uuid4(),
        )


async def test_resolve_reject_refunds_balance_and_stock(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    student = await _seed_membership(membership_repo_for, institution_id)
    admin = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.INSTITUTION_ADMIN
    )
    await _seed_balance(currency_repo_for, institution_id, student.id, 50)
    market_repo = await market_repo_for(institution_id)
    privilege = _new_privilege(institution_id=institution_id, price=20, stock=1)
    await market_repo.add_privilege(privilege)
    purchase = await market_repo.purchase(
        membership_id=student.id,
        privilege_id=privilege.id,
        expected_price=20,
        operation_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )

    rejected = await market_repo.resolve_reject(
        purchase.id,
        resolved_by_membership_id=admin.id,
        now=datetime.now(UTC),
        refund_operation_id=uuid.uuid4(),
    )
    again = await market_repo.resolve_reject(
        purchase.id,
        resolved_by_membership_id=admin.id,
        now=datetime.now(UTC),
        refund_operation_id=uuid.uuid4(),
    )

    assert rejected.status is PurchaseStatus.REJECTED
    assert again.status is PurchaseStatus.REJECTED
    balance = await (await currency_repo_for(institution_id)).get_balance(student.id)
    assert balance == 50
    fresh_privilege = await market_repo.get_privilege(privilege.id)
    assert fresh_privilege.stock == 1


async def test_resolve_fulfil_of_unknown_purchase_is_not_found(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_id = await _seed_institution(institution_repo)
    admin = await _seed_membership(
        membership_repo_for, institution_id, role=UserRole.INSTITUTION_ADMIN
    )
    market_repo = await market_repo_for(institution_id)

    with pytest.raises(PurchaseNotFoundError):
        await market_repo.resolve_fulfil(
            uuid.uuid4(), resolved_by_membership_id=admin.id, now=datetime.now(UTC)
        )


async def test_list_purchases_does_not_see_other_institution(market_repos) -> None:
    institution_repo, membership_repo_for, currency_repo_for, market_repo_for = (
        market_repos
    )
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    student_a = await _seed_membership(membership_repo_for, institution_a)
    await _seed_balance(currency_repo_for, institution_a, student_a.id, 50)
    market_repo_a = await market_repo_for(institution_a)
    privilege_a = _new_privilege(institution_id=institution_a, price=10)
    await market_repo_a.add_privilege(privilege_a)
    await market_repo_a.purchase(
        membership_id=student_a.id,
        privilege_id=privilege_a.id,
        expected_price=10,
        operation_id=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )

    market_repo_b = await market_repo_for(institution_b)
    purchases_b = await market_repo_b.list_purchases(
        status=None, membership_id=None, limit=None
    )
    assert purchases_b == []
