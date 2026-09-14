"""Use case'ы маркета — на фейках (план 07, Ч1, раздел 5 «Тесты и проверка»)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import InsufficientRoleError
from app.business.domain.enums import InstitutionKind, PurchaseStatus
from app.business.domain.errors import (
    InsufficientBalanceError,
    OperationIdConflictError,
    OutOfStockError,
    PriceChangedError,
    PrivilegeNotFoundError,
    PurchaseAlreadyResolvedError,
)
from app.business.use_cases.currency import CreateAccrual, CreateReversal, GetMyCurrency
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import AcceptInvitation, CreateInvitation
from app.business.use_cases.market import (
    CreatePrivilege,
    CreatePurchase,
    FulfilPurchase,
    ListMyPurchases,
    ListPrivileges,
    ListPurchases,
    RejectPurchase,
    UpdatePrivilege,
)
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def uow(store: InMemoryStore) -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork(store)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime.now(UTC))


async def _create_institution(uow, clock, admin_id):
    return await CreateInstitution(uow, clock).execute(
        name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=admin_id
    )


async def _invite_student(uow, clock, institution_id, admin_id, student_id) -> None:
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution_id,
        actor_user_id=admin_id,
        actor_institution_id=institution_id,
        max_uses=1,
    )
    await AcceptInvitation(uow, clock).execute(
        user_id=student_id, token=invitation.token
    )


async def _accrue(uow, clock, institution_id, admin_id, student_id, amount) -> None:
    await CreateAccrual(uow, clock).execute(
        institution_id=institution_id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution_id,
        operation_id=uuid.uuid4(),
        amount=amount,
        comment=None,
    )


async def _create_privilege(
    uow, clock, institution_id, admin_id, *, price=30, stock=None, is_active=True
):
    return await CreatePrivilege(uow, clock).execute(
        institution_id=institution_id,
        actor_user_id=admin_id,
        actor_institution_id=institution_id,
        title="Кофе",
        description=None,
        price=price,
        stock=stock,
        is_active=is_active,
    )


async def _setup(uow, clock, *, price=30, stock=None, balance=60):
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    privilege = await _create_privilege(
        uow, clock, institution.id, admin_id, price=price, stock=stock
    )
    if balance:
        await _accrue(uow, clock, institution.id, admin_id, student_id, balance)
    return institution, admin_id, student_id, privilege


async def test_only_admin_manages_catalogue(uow, clock) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    async with uow as opened:
        from app.business.domain.entities import Membership
        from app.business.domain.enums import MembershipStatus, UserRole

        scope = await opened.for_institution(institution.id)
        await scope.memberships.add(
            Membership(
                id=uuid.uuid4(),
                user_id=teacher_id,
                institution_id=institution.id,
                role=UserRole.TEACHER,
                status=MembershipStatus.ACTIVE,
                created_at=clock.now(),
            )
        )
        await opened.commit()

    with pytest.raises(InsufficientRoleError):
        await CreatePrivilege(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            title="Кофе",
            description=None,
            price=10,
            stock=None,
            is_active=True,
        )


async def test_student_does_not_see_inactive_privileges(uow, clock) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    await _create_privilege(uow, clock, institution.id, admin_id, is_active=True)
    hidden = await _create_privilege(
        uow, clock, institution.id, admin_id, is_active=False
    )

    student_view = await ListPrivileges(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    admin_view = await ListPrivileges(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    assert hidden.id not in {p.id for p in student_view}
    assert hidden.id in {p.id for p in admin_view}


async def test_purchase_debits_balance_and_stock(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=30, stock=3, balance=60
    )

    view, created = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=30,
    )

    assert created is True
    assert view.status is PurchaseStatus.PENDING

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 30

    catalogue = await ListPrivileges(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert next(p for p in catalogue if p.id == privilege.id).stock == 2


async def test_repeated_purchase_operation_id_returns_same_record(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(uow, clock, price=30)
    operation_id = uuid.uuid4()
    purchase = CreatePurchase(uow, clock)

    first, first_created = await purchase.execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        privilege_id=privilege.id,
        expected_price=30,
    )
    second, second_created = await purchase.execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        privilege_id=privilege.id,
        expected_price=30,
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 30
    # _setup начисляет баланс отдельной операцией (60), покупка списывает
    # 30 одной записью независимо от того, сколько раз повторён запрос
    # (идемпотентность) — в истории ровно два начисления: accrual + purchase.
    assert len(account.transactions) == 2


async def test_repeated_purchase_operation_id_with_different_body_is_conflict(
    uow, clock
) -> None:
    institution, admin_id, student_id, privilege = await _setup(uow, clock, price=30)
    other_privilege = await _create_privilege(
        uow, clock, institution.id, admin_id, price=20
    )
    operation_id = uuid.uuid4()
    await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        privilege_id=privilege.id,
        expected_price=30,
    )

    with pytest.raises(OperationIdConflictError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=operation_id,
            privilege_id=other_privilege.id,
            expected_price=20,
        )


async def test_purchase_with_stale_expected_price_is_rejected(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(uow, clock, price=30)
    await UpdatePrivilege(uow, clock).execute(
        institution_id=institution.id,
        privilege_id=privilege.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        fields=frozenset({"price"}),
        title=None,
        description=None,
        price=40,
        stock=None,
        is_active=None,
    )

    with pytest.raises(PriceChangedError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=privilege.id,
            expected_price=30,
        )


async def test_purchase_out_of_stock_is_rejected(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=10, stock=1, balance=100
    )
    await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=10,
    )

    with pytest.raises(OutOfStockError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=privilege.id,
            expected_price=10,
        )


async def test_purchase_hidden_privilege_is_not_found(uow, clock) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    await _accrue(uow, clock, institution.id, admin_id, student_id, 50)
    hidden = await _create_privilege(
        uow, clock, institution.id, admin_id, price=10, is_active=False
    )

    with pytest.raises(PrivilegeNotFoundError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=hidden.id,
            expected_price=10,
        )


async def test_purchase_insufficient_balance_is_rejected(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=50, balance=20
    )

    with pytest.raises(InsufficientBalanceError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=privilege.id,
            expected_price=50,
        )


async def test_purchase_with_balance_exactly_equal_to_price_succeeds(
    uow, clock
) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=50, balance=50
    )

    view, created = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=50,
    )

    assert created is True
    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 0


async def test_reject_refunds_balance_and_stock(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=30, stock=2, balance=60
    )
    purchase_view, _ = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=30,
    )

    rejected = await RejectPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    assert rejected.status is PurchaseStatus.REJECTED

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 60

    catalogue = await ListPrivileges(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert next(p for p in catalogue if p.id == privilege.id).stock == 2


async def test_reject_is_idempotent_and_fulfil_after_reject_is_conflict(
    uow, clock
) -> None:
    institution, admin_id, student_id, privilege = await _setup(uow, clock, price=30)
    purchase_view, _ = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=30,
    )

    first = await RejectPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    second = await RejectPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert first.status is second.status is PurchaseStatus.REJECTED

    with pytest.raises(PurchaseAlreadyResolvedError):
        await FulfilPurchase(uow, clock).execute(
            institution_id=institution.id,
            purchase_id=purchase_view.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
        )


async def test_fulfil_is_idempotent(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(uow, clock, price=30)
    purchase_view, _ = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=30,
    )

    first = await FulfilPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    second = await FulfilPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert first.status is second.status is PurchaseStatus.FULFILLED


async def test_reversal_after_purchase_spending_is_insufficient_balance(
    uow, clock
) -> None:
    """В4/RV1: +100 начислено, 80 потрачено на покупку, сторно −100 → 409."""
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    accrual, _ = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=100,
        comment=None,
    )
    privilege = await _create_privilege(uow, clock, institution.id, admin_id, price=80)
    await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=80,
    )

    with pytest.raises(InsufficientBalanceError):
        await CreateReversal(uow, clock).execute(
            institution_id=institution.id,
            transaction_id=accrual.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
        )

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 20


async def test_balance_equals_sum_of_history(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=30, stock=2, balance=100
    )
    purchase_view, _ = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=30,
    )
    await RejectPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == sum(tx.amount for tx in account.transactions)
    assert account.balance == 100


async def test_admin_list_purchases_pending_without_limit_and_status_filter(
    uow, clock
) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=10, balance=100
    )
    purchase_view, _ = await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=10,
    )
    await FulfilPurchase(uow, clock).execute(
        institution_id=institution.id,
        purchase_id=purchase_view.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    pending = await ListPurchases(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        status=PurchaseStatus.PENDING,
        user_id=None,
    )
    assert pending == []

    everything = await ListPurchases(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        status=None,
        user_id=None,
    )
    assert len(everything) == 1
    assert everything[0].user_id == student_id


async def test_student_cannot_purchase_as_teacher_role(uow, clock) -> None:
    from app.business.domain.entities import Membership
    from app.business.domain.enums import MembershipStatus, UserRole

    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    async with uow as opened:
        scope = await opened.for_institution(institution.id)
        await scope.memberships.add(
            Membership(
                id=uuid.uuid4(),
                user_id=teacher_id,
                institution_id=institution.id,
                role=UserRole.TEACHER,
                status=MembershipStatus.ACTIVE,
                created_at=clock.now(),
            )
        )
        await opened.commit()
    privilege = await _create_privilege(uow, clock, institution.id, admin_id, price=10)

    with pytest.raises(InsufficientRoleError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=privilege.id,
            expected_price=10,
        )


async def test_purchase_of_unknown_privilege_is_not_found(uow, clock) -> None:
    institution, admin_id, student_id, _privilege = await _setup(
        uow, clock, price=10, balance=50
    )

    with pytest.raises(PrivilegeNotFoundError):
        await CreatePurchase(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            privilege_id=uuid.uuid4(),
            expected_price=10,
        )


async def test_list_my_purchases_returns_own_purchases(uow, clock) -> None:
    institution, admin_id, student_id, privilege = await _setup(
        uow, clock, price=10, balance=50
    )
    await CreatePurchase(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        privilege_id=privilege.id,
        expected_price=10,
    )

    mine = await ListMyPurchases(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert len(mine) == 1
    assert mine[0].user_id is None
