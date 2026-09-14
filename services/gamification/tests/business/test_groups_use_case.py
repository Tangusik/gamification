"""Use case'ы групп — на фейках (Ч2б плана, критерии Ч4)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import InsufficientRoleError
from app.business.domain.entities import Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import (
    GroupNameTakenError,
    GroupNotFoundError,
    MemberNotFoundError,
)
from app.business.use_cases.groups import (
    AddGroupStudent,
    AddGroupTeacher,
    CreateGroup,
    DeleteGroup,
    ListGroups,
    RemoveGroupStudent,
    UpdateGroup,
)
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import AcceptInvitation, CreateInvitation
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


async def test_student_cannot_create_group(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    with pytest.raises(InsufficientRoleError):
        await CreateGroup(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            name="Группа",
        )


async def test_group_name_is_unique_case_insensitively(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    create = CreateGroup(uow, clock)
    await create.execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Кружок",
    )

    with pytest.raises(GroupNameTakenError):
        await create.execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            name="кружок",
        )


async def test_rename_to_foreign_group_name_conflicts(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    create = CreateGroup(uow, clock)
    await create.execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Первая",
    )
    second = await create.execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Вторая",
    )

    with pytest.raises(GroupNameTakenError):
        await UpdateGroup(uow).execute(
            institution_id=institution.id,
            group_id=second.id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
            name="первая",
        )


async def test_group_of_other_institution_is_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution_a.id,
        actor_user_id=admin_a,
        actor_institution_id=institution_a.id,
        name="Группа",
    )

    with pytest.raises(GroupNotFoundError):
        await UpdateGroup(uow).execute(
            institution_id=institution_b.id,
            group_id=group.id,
            actor_user_id=admin_b,
            actor_institution_id=institution_b.id,
            name="Новое имя",
        )
    with pytest.raises(GroupNotFoundError):
        await DeleteGroup(uow).execute(
            institution_id=institution_b.id,
            group_id=group.id,
            actor_user_id=admin_b,
            actor_institution_id=institution_b.id,
        )


async def test_student_as_group_teacher_is_member_not_found(
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

    with pytest.raises(MemberNotFoundError):
        await AddGroupTeacher(uow).execute(
            institution_id=institution.id,
            group_id=group.id,
            target_user_id=student_id,
            actor_user_id=admin_id,
            actor_institution_id=institution.id,
        )


async def test_add_teacher_to_group_of_other_institution_is_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    await _add_teacher(uow, clock, institution_b.id, teacher_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution_a.id,
        actor_user_id=admin_a,
        actor_institution_id=institution_a.id,
        name="Группа",
    )

    with pytest.raises(GroupNotFoundError):
        await AddGroupTeacher(uow).execute(
            institution_id=institution_b.id,
            group_id=group.id,
            target_user_id=teacher_id,
            actor_user_id=admin_b,
            actor_institution_id=institution_b.id,
        )


async def test_add_teacher_from_other_institution_is_member_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    await _add_teacher(uow, clock, institution_b.id, teacher_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution_a.id,
        actor_user_id=admin_a,
        actor_institution_id=institution_a.id,
        name="Группа",
    )

    with pytest.raises(MemberNotFoundError):
        await AddGroupTeacher(uow).execute(
            institution_id=institution_a.id,
            group_id=group.id,
            target_user_id=teacher_id,
            actor_user_id=admin_a,
            actor_institution_id=institution_a.id,
        )


async def test_add_student_from_other_institution_is_member_not_found(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_a = uuid.uuid4()
    admin_b = uuid.uuid4()
    student_id = uuid.uuid4()
    institution_a = await _create_institution(uow, clock, admin_a)
    institution_b = await _create_institution(uow, clock, admin_b)
    await _invite_student(uow, clock, institution_b.id, admin_b, student_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution_a.id,
        actor_user_id=admin_a,
        actor_institution_id=institution_a.id,
        name="Группа",
    )

    with pytest.raises(MemberNotFoundError):
        await AddGroupStudent(uow).execute(
            institution_id=institution_a.id,
            group_id=group.id,
            target_user_id=student_id,
            actor_user_id=admin_a,
            actor_institution_id=institution_a.id,
        )


async def test_add_group_teacher_is_idempotent(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Группа",
    )
    add_teacher = AddGroupTeacher(uow)

    await add_teacher.execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=teacher_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    await add_teacher.execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=teacher_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    groups = await ListGroups(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert groups[0].teacher_ids == [teacher_id]


async def test_delete_group_removes_only_connections(
    uow: InMemoryUnitOfWork, clock: FixedClock, store: InMemoryStore
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    await _add_teacher(uow, clock, institution.id, teacher_id)
    await _invite_student(uow, clock, institution.id, admin_id, student_id)

    group_to_delete = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Удаляемая",
    )
    other_group = await CreateGroup(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        name="Остающаяся",
    )
    await AddGroupTeacher(uow).execute(
        institution_id=institution.id,
        group_id=group_to_delete.id,
        target_user_id=teacher_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    add_student = AddGroupStudent(uow)
    await add_student.execute(
        institution_id=institution.id,
        group_id=group_to_delete.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    await add_student.execute(
        institution_id=institution.id,
        group_id=other_group.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    memberships_before = dict(store.memberships)

    await DeleteGroup(uow).execute(
        institution_id=institution.id,
        group_id=group_to_delete.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    # Члены остаются — удаление группы снимает только связи.
    assert store.memberships == memberships_before
    remaining = await ListGroups(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    assert [group.id for group in remaining] == [other_group.id]
    assert remaining[0].students_count == 1


async def test_remove_group_student_is_idempotent(
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
    remove_student = RemoveGroupStudent(uow)

    # Открепление того, кто и не был прикреплён — идемпотентно, без ошибки.
    await remove_student.execute(
        institution_id=institution.id,
        group_id=group.id,
        target_user_id=student_id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
