"""Use case'ы создания учреждения и списка своих членств — на фейках."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.use_cases.institutions import CreateInstitution, ListMyInstitutions
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork


class FixedClock:
    """Фейковые часы: use case не должен зависеть от системного времени."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment


class FailingMembershipsScope:
    """Фейк, гарантированно срывающий вставку членства."""

    def __init__(self, real_scope) -> None:
        self._real_scope = real_scope
        self.memberships = self

    async def add(self, membership) -> None:
        raise RuntimeError("boom")

    async def get_for_user(self, user_id):
        return await self._real_scope.memberships.get_for_user(user_id)


class FailOnMembershipUnitOfWork(InMemoryUnitOfWork):
    """UnitOfWork, срывающий вставку членства — проверка атомарности."""

    async def for_institution(self, institution_id):
        return FailingMembershipsScope(await super().for_institution(institution_id))


@pytest.fixture
def store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def uow(store: InMemoryStore) -> InMemoryUnitOfWork:
    return InMemoryUnitOfWork(store)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime.now(UTC))


async def test_create_institution_creates_admin_membership_in_one_transaction(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    """Учреждение и членство создателя появляются одним актом (E1)."""
    created_by = uuid.uuid4()
    use_case = CreateInstitution(uow, clock)

    institution = await use_case.execute(
        name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=created_by
    )

    scope = await uow.for_institution(institution.id)
    membership = await scope.memberships.get_for_user(created_by)
    assert membership is not None
    assert membership.role is UserRole.INSTITUTION_ADMIN
    assert membership.status is MembershipStatus.ACTIVE


async def test_failure_after_institution_insert_leaves_nothing(
    store: InMemoryStore, clock: FixedClock
) -> None:
    """Сбой после вставки учреждения не оставляет ни его, ни членства."""
    uow = FailOnMembershipUnitOfWork(store)
    use_case = CreateInstitution(uow, clock)

    with pytest.raises(RuntimeError):
        await use_case.execute(
            name="Школа", kind=InstitutionKind.SCHOOL, created_by=uuid.uuid4()
        )

    assert store.institutions == {}
    assert store.memberships == {}


async def test_list_my_institutions_hides_foreign_institutions(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    """Чужое учреждение не видно (раздел этапа 3, критерий готовности)."""
    owner = uuid.uuid4()
    stranger = uuid.uuid4()
    create = CreateInstitution(uow, clock)
    institution = await create.execute(
        name="Школа", kind=InstitutionKind.SCHOOL, created_by=owner
    )

    listing = ListMyInstitutions(uow)
    stranger_views = await listing.execute(user_id=stranger)
    owner_views = await listing.execute(user_id=owner)

    assert stranger_views == []
    assert len(owner_views) == 1
    assert owner_views[0].institution_id == institution.id
    assert owner_views[0].role is UserRole.INSTITUTION_ADMIN
    assert owner_views[0].status is MembershipStatus.ACTIVE
