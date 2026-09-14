"""Use case переключения учреждения — на фейках ``TokenIssuer`` (раздел 4)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.access_errors import NotAMemberError
from app.business.domain.entities import Membership
from app.business.domain.enums import MembershipStatus, UserRole
from app.business.domain.errors import (
    SubjectTokenRejectedError,
    TokenIssuerContractError,
    TokenIssuerUnavailableError,
)
from app.business.use_cases.context import SwitchInstitution
from app.repositories.in_memory import InMemoryStore
from app.repositories.uow import InMemoryUnitOfWork


class FakeTokenIssuer:
    """Фейк порта ``TokenIssuer``: либо отдаёт токен, либо бросает ошибку."""

    def __init__(
        self, *, token: str | None = None, error: Exception | None = None
    ) -> None:
        self._token = token
        self._error = error

    async def issue_context_token(
        self, *, subject_token: str, institution_id: uuid.UUID, role: str
    ) -> str:
        if self._error is not None:
            raise self._error
        assert self._token is not None
        return self._token


async def _seed_membership(
    uow: InMemoryUnitOfWork,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    *,
    role: UserRole = UserRole.STUDENT,
    status: MembershipStatus = MembershipStatus.ACTIVE,
) -> None:
    membership = Membership(
        id=uuid.uuid4(),
        user_id=user_id,
        institution_id=institution_id,
        role=role,
        status=status,
        created_at=datetime.now(UTC),
    )
    async with uow as transaction:
        scope = await transaction.for_institution(institution_id)
        await scope.memberships.add(membership)
        await transaction.commit()


async def test_switch_without_membership_is_rejected_without_calling_users() -> None:
    uow = InMemoryUnitOfWork(InMemoryStore())
    use_case = SwitchInstitution(uow, FakeTokenIssuer(token="unexpected"))

    with pytest.raises(NotAMemberError):
        await use_case.execute(
            user_id=uuid.uuid4(), institution_id=uuid.uuid4(), subject_token="T0"
        )


async def test_switch_with_suspended_membership_is_rejected() -> None:
    store = InMemoryStore()
    uow = InMemoryUnitOfWork(store)
    user_id, institution_id = uuid.uuid4(), uuid.uuid4()
    await _seed_membership(
        uow, user_id, institution_id, status=MembershipStatus.SUSPENDED
    )
    use_case = SwitchInstitution(uow, FakeTokenIssuer(token="unexpected"))

    with pytest.raises(NotAMemberError):
        await use_case.execute(
            user_id=user_id, institution_id=institution_id, subject_token="T0"
        )


async def test_switch_succeeds_for_active_member() -> None:
    store = InMemoryStore()
    uow = InMemoryUnitOfWork(store)
    user_id, institution_id = uuid.uuid4(), uuid.uuid4()
    await _seed_membership(uow, user_id, institution_id, role=UserRole.TEACHER)
    use_case = SwitchInstitution(uow, FakeTokenIssuer(token="T1"))

    result = await use_case.execute(
        user_id=user_id, institution_id=institution_id, subject_token="T0"
    )

    assert result.access_token == "T1"
    assert result.token_type == "bearer"


@pytest.mark.parametrize(
    "error",
    [
        TokenIssuerUnavailableError(),
        SubjectTokenRejectedError(),
        TokenIssuerContractError(),
    ],
    ids=["users_unavailable_or_401", "users_rejected_403", "users_malformed_422"],
)
async def test_switch_propagates_each_users_failure_as_its_own_error(
    error: Exception,
) -> None:
    """users недоступен/401, отказал 403 или ответил не по контракту 422 —
    каждый исход своим доменным типом (раздел 4.2)."""
    store = InMemoryStore()
    uow = InMemoryUnitOfWork(store)
    user_id, institution_id = uuid.uuid4(), uuid.uuid4()
    await _seed_membership(uow, user_id, institution_id)
    use_case = SwitchInstitution(uow, FakeTokenIssuer(error=error))

    with pytest.raises(type(error)):
        await use_case.execute(
            user_id=user_id, institution_id=institution_id, subject_token="T0"
        )
