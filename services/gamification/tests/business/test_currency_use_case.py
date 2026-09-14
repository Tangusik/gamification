"""Use case'ы валюты — на фейках (Ч1 плана 06, раздел 5 «Тесты и проверка»)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import InsufficientRoleError
from app.business.domain.entities import Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import (
    MemberNotFoundError,
    OperationIdConflictError,
    StudentSuspendedError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
)
from app.business.use_cases.currency import (
    CreateAccrual,
    CreateReversal,
    GetMyCurrency,
)
from app.business.use_cases.groups import AddGroupStudent, AddGroupTeacher, CreateGroup
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import AcceptInvitation, CreateInvitation
from app.business.use_cases.students import UpdateStudent
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


async def _create_institution(uow: InMemoryUnitOfWork, clock: FixedClock, admin_id):
    return await CreateInstitution(uow, clock).execute(
        name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=admin_id
    )


async def _add_teacher(uow, clock, institution_id, teacher_id) -> None:
    async with uow as opened:
        scope = await opened.for_institution(institution_id)
        await scope.memberships.add(
            Membership(
                id=uuid.uuid4(),
                user_id=teacher_id,
                institution_id=institution_id,
                role=UserRole.TEACHER,
                status=MembershipStatus.ACTIVE,
                created_at=clock.now(),
            )
        )
        await opened.commit()


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


async def test_teacher_accrues_to_student_of_own_group(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Группа",
    )
    await AddGroupTeacher(uow).execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=teacher_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    await AddGroupStudent(uow).execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    view, created = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=teacher_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=50,
        comment="За олимпиаду",
    )

    assert created is True
    assert view.amount == 50
    assert view.created_by_role is UserRole.TEACHER

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 50
    assert len(account.transactions) == 1


async def test_teacher_cannot_accrue_to_student_of_other_group(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    other_group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Чужая группа",
    )
    await AddGroupStudent(uow).execute(
        institution_id=institution.id,
        group_id=other_group.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    with pytest.raises(MemberNotFoundError):
        await CreateAccrual(uow, clock).execute(
            institution_id=institution.id,
            target_user_id=student_id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            amount=10,
            comment=None,
        )


async def test_teacher_cannot_accrue_to_student_of_other_institution(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    await _add_teacher(uow, clock, institution_a.id, teacher_id)
    await _invite_student(uow, clock, institution_b.id, admin_b, student_id)

    with pytest.raises(MemberNotFoundError):
        await CreateAccrual(uow, clock).execute(
            institution_id=institution_a.id,
            target_user_id=student_id,
            actor_user_id=teacher_id,
            actor_institution_id=institution_a.id,
            operation_id=uuid.uuid4(),
            amount=10,
            comment=None,
        )


async def test_admin_accrues_to_any_student_without_groups(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    view, created = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=20,
        comment=None,
    )

    assert created is True
    assert view.created_by_role is UserRole.INSTITUTION_ADMIN


async def test_student_cannot_create_accrual(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    other_student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    await _invite_student(uow, clock, institution.id, admin_id, other_student_id)

    with pytest.raises(InsufficientRoleError):
        await CreateAccrual(uow, clock).execute(
            institution_id=institution.id,
            target_user_id=other_student_id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            amount=10,
            comment=None,
        )


async def test_accrual_to_suspended_student_is_rejected(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    await UpdateStudent(uow).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        display_name=None,
        status=MembershipStatus.SUSPENDED,
    )

    with pytest.raises(StudentSuspendedError):
        await CreateAccrual(uow, clock).execute(
            institution_id=institution.id,
            target_user_id=student_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
            amount=10,
            comment=None,
        )


async def test_empty_comment_after_trim_is_stored_as_none(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    view, _ = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=10,
        comment=None,
    )

    assert view.comment is None


async def test_repeated_operation_id_with_same_body_returns_same_record(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    operation_id = uuid.uuid4()
    create = CreateAccrual(uow, clock)

    first_view, first_created = await create.execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        amount=15,
        comment="Причина",
    )
    second_view, second_created = await create.execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        amount=15,
        comment="Причина",
    )

    assert first_created is True
    assert second_created is False
    assert first_view.id == second_view.id

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 15
    assert len(account.transactions) == 1


async def test_repeated_operation_id_with_different_body_is_conflict(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    operation_id = uuid.uuid4()
    create = CreateAccrual(uow, clock)
    await create.execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
        amount=15,
        comment=None,
    )

    with pytest.raises(OperationIdConflictError):
        await create.execute(
            institution_id=institution.id,
            target_user_id=student_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            operation_id=operation_id,
            amount=99,
            comment=None,
        )


async def test_student_in_two_groups_of_same_teacher_gets_one_accrual(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    group_a = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="А",
    )
    group_b = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Б",
    )
    add_teacher = AddGroupTeacher(uow)
    add_student = AddGroupStudent(uow)
    for group in (group_a, group_b):
        await add_teacher.execute(
            institution_id=institution.id,
            group_id=group.id,
            target_user_id=teacher_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
        )
        await add_student.execute(
            institution_id=institution.id,
            group_id=group.id,
            target_user_id=student_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
        )

    view, created = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=teacher_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=25,
        comment=None,
    )

    assert created is True

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 25
    assert len(account.transactions) == 1
    assert view.amount == 25


async def test_reversal_by_admin_decreases_balance(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
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
        amount=40,
        comment=None,
    )

    reversal, created = await CreateReversal(uow, clock).execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
    )

    assert created is True
    assert reversal.amount == -40
    assert reversal.reverses_id == accrual.id

    account = await GetMyCurrency(uow).execute(
        institution_id=institution.id,
        actor_user_id=student_id,
        actor_institution_id=institution.id,
    )
    assert account.balance == 0
    assert len(account.transactions) == 2


async def test_teacher_cannot_reverse(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    accrual, _ = await CreateAccrual(uow, clock).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
        amount=40,
        comment=None,
    )

    with pytest.raises(InsufficientRoleError):
        await CreateReversal(uow, clock).execute(
            institution_id=institution.id,
            transaction_id=accrual.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
        )


async def test_repeated_reversal_operation_id_returns_same_record(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
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
        amount=40,
        comment=None,
    )
    operation_id = uuid.uuid4()
    reverse = CreateReversal(uow, clock)

    first, first_created = await reverse.execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
    )
    second, second_created = await reverse.execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=operation_id,
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id


async def test_reversing_already_reversed_transaction_with_new_operation_id_fails(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
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
        amount=40,
        comment=None,
    )
    reverse = CreateReversal(uow, clock)
    await reverse.execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
    )

    with pytest.raises(TransactionAlreadyReversedError):
        await reverse.execute(
            institution_id=institution.id,
            transaction_id=accrual.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
        )


async def test_reversing_a_reversal_is_transaction_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
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
        amount=40,
        comment=None,
    )
    reversal, _ = await CreateReversal(uow, clock).execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
    )

    with pytest.raises(TransactionNotFoundError):
        await CreateReversal(uow, clock).execute(
            institution_id=institution.id,
            transaction_id=reversal.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            operation_id=uuid.uuid4(),
        )


async def test_reversal_of_suspended_students_accrual_is_allowed(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    """Сторно приостановленному ученику разрешено — это исправление, а не
    начисление (план 06, «Уточнения к семантике»)."""
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
        amount=40,
        comment=None,
    )
    await UpdateStudent(uow).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        display_name=None,
        status=MembershipStatus.SUSPENDED,
    )

    _, created = await CreateReversal(uow, clock).execute(
        institution_id=institution.id,
        transaction_id=accrual.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        operation_id=uuid.uuid4(),
    )

    assert created is True
