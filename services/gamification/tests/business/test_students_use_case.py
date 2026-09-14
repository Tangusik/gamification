"""Use case'ы учеников — на фейках (Ч2в плана, критерии Ч4)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import InsufficientRoleError
from app.business.domain.entities import Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import GroupNotFoundError, MemberNotFoundError
from app.business.use_cases.groups import (
    AddGroupStudent,
    AddGroupTeacher,
    CreateGroup,
)
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import AcceptInvitation, CreateInvitation
from app.business.use_cases.students import ListStudents, UpdateStudent
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


async def _invite_student(uow, clock, institution_id, admin_id, student_id):
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution_id,
        actor_user_id=admin_id,
        actor_institution_id=institution_id,
        max_uses=1,
    )
    await AcceptInvitation(uow, clock).execute(
        user_id=student_id, token=invitation.token
    )


async def test_student_cannot_list_students(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    """У7/В1-А2 (план 06): список учеников доступен teacher и admin, но
    не student.
    """
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    with pytest.raises(InsufficientRoleError):
        await ListStudents(uow).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            group_id=None,
        )


async def test_teacher_sees_only_students_of_own_groups(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    """План 06, «Доступ преподавателя»: teacher видит только учеников
    своих групп, а не всё учреждение.
    """
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    own_student_id = uuid.uuid4()
    other_student_id = uuid.uuid4()
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
    await _invite_student(uow, clock, institution.id, admin_id, own_student_id)
    await _invite_student(uow, clock, institution.id, admin_id, other_student_id)

    own_group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Своя группа",
    )
    other_group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Чужая группа",
    )
    await AddGroupTeacher(uow).execute(
        institution_id=institution.id,
        group_id=own_group.id,
        target_user_id=teacher_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    add_student = AddGroupStudent(uow)
    await add_student.execute(
        institution_id=institution.id,
        group_id=own_group.id,
        target_user_id=own_student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    await add_student.execute(
        institution_id=institution.id,
        group_id=other_group.id,
        target_user_id=other_student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    visible = await ListStudents(uow).execute(
        institution_id=institution.id,
        actor_user_id=teacher_id,
        actor_institution_id=institution.id,
        group_id=None,
    )

    assert [student.user_id for student in visible] == [own_student_id]

    with pytest.raises(GroupNotFoundError):
        await ListStudents(uow).execute(
            institution_id=institution.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
            group_id=other_group.id,
        )


async def test_list_students_with_unknown_group_is_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)

    with pytest.raises(GroupNotFoundError):
        await ListStudents(uow).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            group_id=uuid.uuid4(),
        )


async def test_student_in_two_groups_appears_with_both_and_filter_works(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    group_a = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Группа А",
    )
    group_b = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Группа Б",
    )
    add_student = AddGroupStudent(uow)
    await add_student.execute(
        institution_id=institution.id,
        group_id=group_a.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    await add_student.execute(
        institution_id=institution.id,
        group_id=group_b.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    # Повтор не должен дублировать связь.
    await add_student.execute(
        institution_id=institution.id,
        group_id=group_a.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    all_students = await ListStudents(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        group_id=None,
    )
    assert len(all_students) == 1
    assert set(all_students[0].group_ids) == {group_a.id, group_b.id}

    only_a = await ListStudents(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        group_id=group_a.id,
    )
    assert len(only_a) == 1


async def test_update_student_rejects_teacher_as_not_found(
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

    with pytest.raises(MemberNotFoundError):
        await UpdateStudent(uow).execute(
            institution_id=institution.id,
            target_user_id=teacher_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            display_name=None,
            status=MembershipStatus.SUSPENDED,
        )


async def test_update_student_suspends_and_keeps_groups(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Группа",
    )
    await AddGroupStudent(uow).execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    updated = await UpdateStudent(uow).execute(
        institution_id=institution.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        display_name=None,
        status=MembershipStatus.SUSPENDED,
    )

    assert updated.status is MembershipStatus.SUSPENDED
    assert updated.group_ids == [group.id]
