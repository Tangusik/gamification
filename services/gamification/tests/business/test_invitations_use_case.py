"""Use case'ы приглашений — на фейках (раздел 5, критерии этапа 4)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import (
    AccessError,
    InstitutionContextRequiredError,
    InsufficientRoleError,
    InvitationInvalidError,
    MembershipSuspendedError,
    NotAMemberError,
)
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.use_cases.institutions import CreateInstitution
from app.business.use_cases.invitations import (
    AcceptInvitation,
    CreateInvitation,
    ListInvitations,
    RevokeInvitation,
)
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork


class FixedClock:
    """Фейковые часы: use case не должен зависеть от системного времени."""

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
    use_case = CreateInstitution(uow, clock)
    return await use_case.execute(
        name="Школа №1", kind=InstitutionKind.SCHOOL, created_by=admin_id
    )


async def test_admin_creates_invitation(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)

    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )

    assert invitation.role is UserRole.STUDENT
    assert invitation.max_uses == 1
    assert invitation.uses_count == 0
    assert invitation.revoked_at is None
    assert invitation.token


async def test_student_cannot_create_invitation(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    accepted = await AcceptInvitation(uow, clock).execute(
        user_id=student_id,
        token=(
            await CreateInvitation(uow, clock).execute(
                institution_id=institution.id,
                actor_user_id=admin_id,
                actor_institution_id=institution.id,
                max_uses=1,
            )
        ).token,
    )
    assert accepted.role is UserRole.STUDENT

    with pytest.raises(InsufficientRoleError):
        await CreateInvitation(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=student_id,
            actor_institution_id=institution.id,
            max_uses=1,
        )


async def test_create_invitation_requires_matching_context(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)

    with pytest.raises(InstitutionContextRequiredError):
        await CreateInvitation(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=uuid.uuid4(),
            max_uses=1,
        )

    with pytest.raises(InstitutionContextRequiredError):
        await CreateInvitation(uow, clock).execute(
            institution_id=institution.id,
            actor_user_id=admin_id,
            actor_institution_id=None,
            max_uses=1,
        )


async def test_teacher_sees_only_own_invitations(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)

    admin_invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )
    # Преподаватель становится членом через собственное приглашение,
    # чтобы принять и создавать приглашения на общих правах (F3).
    await AcceptInvitation(uow, clock).execute(
        user_id=teacher_id, token=admin_invitation.token
    )
    scope = await uow.for_institution(institution.id)
    membership = await scope.memberships.get_for_user(teacher_id)
    membership.role = UserRole.TEACHER
    # InMemory-репозиторий отдаёт копии; правим напрямую через store.
    stored = uow._store.memberships[membership.id]  # noqa: SLF001
    stored.role = UserRole.TEACHER

    teacher_invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=teacher_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )

    teacher_view = await ListInvitations(uow).execute(
        institution_id=institution.id,
        actor_user_id=teacher_id,
        actor_institution_id=institution.id,
    )
    admin_view = await ListInvitations(uow).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    assert [item.id for item in teacher_view] == [teacher_invitation.id]
    assert {item.id for item in admin_view} == {
        admin_invitation.id,
        teacher_invitation.id,
    }


async def test_teacher_cannot_revoke_foreign_invitation(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    teacher_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    admin_invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )
    await AcceptInvitation(uow, clock).execute(
        user_id=teacher_id, token=admin_invitation.token
    )
    scope = await uow.for_institution(institution.id)
    membership = await scope.memberships.get_for_user(teacher_id)
    uow._store.memberships[membership.id].role = UserRole.TEACHER  # noqa: SLF001

    other_invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )

    with pytest.raises(InvitationInvalidError):
        await RevokeInvitation(uow).execute(
            institution_id=institution.id,
            invitation_id=other_invitation.id,
            actor_user_id=teacher_id,
            actor_institution_id=institution.id,
        )


async def test_admin_revokes_any_invitation_idempotently(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )

    revoke = RevokeInvitation(uow)
    await revoke.execute(
        institution_id=institution.id,
        invitation_id=invitation.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )
    # Повторный отзыв уже отозванного — идемпотентно, без ошибки.
    await revoke.execute(
        institution_id=institution.id,
        invitation_id=invitation.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
    )

    with pytest.raises(InvitationInvalidError):
        await AcceptInvitation(uow, clock).execute(
            user_id=uuid.uuid4(), token=invitation.token
        )


async def test_accept_unknown_token_is_invalid(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    with pytest.raises(InvitationInvalidError):
        await AcceptInvitation(uow, clock).execute(
            user_id=uuid.uuid4(), token="does-not-exist"
        )


async def test_accept_exhausted_invitation_is_invalid(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )

    await AcceptInvitation(uow, clock).execute(
        user_id=uuid.uuid4(), token=invitation.token
    )

    with pytest.raises(InvitationInvalidError):
        await AcceptInvitation(uow, clock).execute(
            user_id=uuid.uuid4(), token=invitation.token
        )


async def test_accept_twice_by_same_user_is_idempotent(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=1,
    )
    accept = AcceptInvitation(uow, clock)

    first = await accept.execute(user_id=student_id, token=invitation.token)
    second = await accept.execute(user_id=student_id, token=invitation.token)

    assert first.institution_id == second.institution_id
    assert first.role is second.role is UserRole.STUDENT
    scope = await uow.for_institution(institution.id)
    stored = await scope.invitations.get(invitation.id)
    assert stored.uses_count == 1


async def test_accept_by_suspended_member_is_rejected_without_reactivation(
    uow: InMemoryUnitOfWork, clock: FixedClock
) -> None:
    admin_id = uuid.uuid4()
    student_id = uuid.uuid4()
    institution = await _create_institution(uow, clock, admin_id)
    invitation = await CreateInvitation(uow, clock).execute(
        institution_id=institution.id,
        actor_user_id=admin_id,
        actor_institution_id=institution.id,
        max_uses=5,
    )
    await AcceptInvitation(uow, clock).execute(
        user_id=student_id, token=invitation.token
    )
    scope = await uow.for_institution(institution.id)
    membership = await scope.memberships.get_for_user(student_id)
    uow._store.memberships[membership.id].status = MembershipStatus.SUSPENDED  # noqa: SLF001

    with pytest.raises(MembershipSuspendedError):
        await AcceptInvitation(uow, clock).execute(
            user_id=student_id, token=invitation.token
        )

    scope = await uow.for_institution(institution.id)
    stored = await scope.invitations.get(invitation.id)
    assert stored.uses_count == 1


def test_access_errors_are_domain_errors() -> None:
    """Страховка от регресса: коды приглашений — часть словаря доступа."""
    assert issubclass(InvitationInvalidError, AccessError)
    assert issubclass(MembershipSuspendedError, AccessError)
    assert issubclass(NotAMemberError, AccessError)
