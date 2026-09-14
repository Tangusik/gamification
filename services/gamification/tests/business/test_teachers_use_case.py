"""Use case'ы преподавателей — на фейках (Ч2а плана, критерии Ч4)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import (
    InstitutionContextRequiredError,
    InsufficientRoleError,
)
from app.business.domain.entities import Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import MemberNotFoundError
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.teachers import CreateTeacher, ListTeachers, UpdateTeacher
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class FakeUserAccounts:
    """Фейк users: выдаёт фиксированный ``user_id`` или бросает ошибку."""

    def __init__(
        self, *, user_id: uuid.UUID | None = None, error: Exception | None = None
    ):
        self._user_id = user_id or uuid.uuid4()
        self._error = error
        self.calls: list[tuple[str, str]] = []

    async def create_account(self, *, email: str, password: str) -> uuid.UUID:
        self.calls.append((email, password))
        if self._error is not None:
            raise self._error
        return self._user_id


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
    use_case = CreateInstitution(uow, clock)
    return await use_case.execute(
        name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=admin_id
    )


async def test_admin_creates_teacher(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    accounts = FakeUserAccounts()

    view = await CreateTeacher(uow, clock, accounts).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        email="teacher@example.com",
        password="correct horse",
        display_name="Иван Иванов",
    )

    assert accounts.calls == [("teacher@example.com", "correct horse")]
    assert view.display_name == "Иван Иванов"
    assert view.status is MembershipStatus.ACTIVE
    scope = await uow.for_institution(institution.id)
    membership = await scope.memberships.get_for_user(view.user_id)
    assert membership is not None
    assert membership.role is UserRole.TEACHER


async def test_create_teacher_requires_admin_role(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
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

    with pytest.raises(InsufficientRoleError):
        await CreateTeacher(uow, clock, FakeUserAccounts()).execute(
            institution_id=institution.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            email="new@example.com",
            password="whatever123",
            display_name="Кто-то",
        )


async def test_create_teacher_requires_matching_context(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)

    with pytest.raises(InstitutionContextRequiredError):
        await CreateTeacher(uow, clock, FakeUserAccounts()).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=uuid.uuid4(),
            email="new@example.com",
            password="whatever123",
            display_name="Кто-то",
        )


async def test_create_teacher_does_not_add_membership_when_users_fails(
    uow: InMemoryUnitOfWork, clock: FixedClock, store: InMemoryStore
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    accounts = FakeUserAccounts(error=RuntimeError("users is down"))
    memberships_before = dict(store.memberships)

    with pytest.raises(RuntimeError):
        await CreateTeacher(uow, clock, accounts).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            email="new@example.com",
            password="whatever123",
            display_name="Кто-то",
        )

    assert store.memberships == memberships_before


async def test_list_teachers_hides_foreign_institution(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    await CreateTeacher(uow, clock, FakeUserAccounts()).execute(
        institution_id=institution_a.id,
        actor_user_id=admin_a,
        actor_institution_id=institution_a.id,
        email="a@example.com",
        password="whatever123",
        display_name="A",
    )

    views_b = await ListTeachers(uow).execute(
        institution_id=institution_b.id,
        actor_user_id=admin_b,
        actor_institution_id=institution_b.id,
    )

    assert views_b == []


async def test_update_teacher_rejects_student_as_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    async with uow as opened:
        scope = await opened.for_institution(institution.id)
        await scope.memberships.add(
            Membership(
                id=uuid.uuid4(),
                user_id=student_id,
                institution_id=institution.id,
                role=UserRole.STUDENT,
                status=MembershipStatus.ACTIVE,
                created_at=clock.now(),
            )
        )
        await opened.commit()

    with pytest.raises(MemberNotFoundError):
        await UpdateTeacher(uow).execute(
            institution_id=institution.id,
            target_user_id=student_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            display_name="Новое имя",
            status=None,
        )


async def test_update_teacher_changes_display_name_and_status(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    created = await CreateTeacher(uow, clock, FakeUserAccounts()).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        email="teacher@example.com",
        password="whatever123",
        display_name="Старое имя",
    )

    updated = await UpdateTeacher(uow).execute(
        institution_id=institution.id,
        target_user_id=created.user_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        display_name="Новое имя",
        status=MembershipStatus.SUSPENDED,
    )

    assert updated.display_name == "Новое имя"
    assert updated.status is MembershipStatus.SUSPENDED


async def test_update_teacher_does_not_clear_display_name_when_omitted(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    created = await CreateTeacher(uow, clock, FakeUserAccounts()).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        email="teacher@example.com",
        password="whatever123",
        display_name="Имя",
    )

    updated = await UpdateTeacher(uow).execute(
        institution_id=institution.id,
        target_user_id=created.user_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        display_name=None,
        status=MembershipStatus.SUSPENDED,
    )

    assert updated.display_name == "Имя"
    assert updated.status is MembershipStatus.SUSPENDED
