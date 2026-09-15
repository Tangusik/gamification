"""Юнит-тесты use case ``refresh_session`` (план 10-refresh, раздел 3).

Тесты идут без HTTP и без хранилища — только фейковые реализации портов
(``MembershipsPort``, ``RefreshSessionRepository``): use case не знает
про каркасы, поэтому и тестировать его можно в изоляции.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.business.domain.entities import InstitutionContext, RefreshSession
from app.business.domain.errors import (
    MembershipCheckUnavailableError,
    MembershipNotActiveError,
)
from app.business.ports import RotationOutcome, RotationResult
from app.business.use_cases.refresh import (
    RefreshOutcome,
    RefreshRejectedError,
    refresh_session,
    resolve_institution_context,
)

USER_ID = uuid.uuid4()
SESSION_ID = uuid.uuid4()
INSTITUTION_A = uuid.uuid4()
INSTITUTION_B = uuid.uuid4()


class FakeMemberships:
    """Двойник ``MembershipsPort``: заранее заданный исход одного вызова."""

    def __init__(
        self, *, role: str | None = None, error: Exception | None = None
    ) -> None:
        self._role = role
        self._error = error
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def resolve_role(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID
    ) -> str:
        self.calls.append((user_id, institution_id))
        if self._error is not None:
            raise self._error
        assert self._role is not None
        return self._role


@dataclass
class FakeRepository:
    """Двойник ``RefreshSessionRepository``: помнит, с чем вызвали ``rotate``."""

    result: RotationResult
    rotate_calls: list[dict[str, object]]

    async def rotate(self, **kwargs: object) -> RotationResult:
        self.rotate_calls.append(kwargs)
        return self.result


def _session(**overrides: object) -> RefreshSession:
    now = datetime.now(UTC)
    defaults: dict[str, object] = dict(
        id=SESSION_ID,
        user_id=USER_ID,
        client="web",
        institution_id=None,
        created_at=now,
        last_used_at=now,
        idle_expires_at=now + timedelta(days=7),
        absolute_expires_at=now + timedelta(days=30),
    )
    defaults.update(overrides)
    return RefreshSession(**defaults)  # type: ignore[arg-type]


# --- resolve_institution_context -----------------------------------------


async def test_no_requested_and_no_remembered_institution_skips_gamification() -> None:
    memberships = FakeMemberships(role="teacher")

    context, stored = await resolve_institution_context(
        memberships,
        user_id=USER_ID,
        requested_institution_id=None,
        remembered_institution_id=None,
    )

    assert context is None
    assert stored is None
    assert memberships.calls == []


async def test_requested_institution_overrides_remembered() -> None:
    memberships = FakeMemberships(role="teacher")

    context, stored = await resolve_institution_context(
        memberships,
        user_id=USER_ID,
        requested_institution_id=INSTITUTION_A,
        remembered_institution_id=INSTITUTION_B,
    )

    assert context == InstitutionContext(institution_id=INSTITUTION_A, role="teacher")
    assert stored == INSTITUTION_A
    assert memberships.calls == [(USER_ID, INSTITUTION_A)]


async def test_empty_requested_institution_falls_back_to_remembered() -> None:
    """У1, вариант А: пустое поле — берётся запомненное."""
    memberships = FakeMemberships(role="student")

    context, stored = await resolve_institution_context(
        memberships,
        user_id=USER_ID,
        requested_institution_id=None,
        remembered_institution_id=INSTITUTION_B,
    )

    assert context == InstitutionContext(institution_id=INSTITUTION_B, role="student")
    assert stored == INSTITUTION_B


async def test_membership_not_active_clears_context_and_session_value() -> None:
    """404 от gamification: без контекста, ``institution_id`` в сессии = NULL."""
    memberships = FakeMemberships(error=MembershipNotActiveError())

    context, stored = await resolve_institution_context(
        memberships,
        user_id=USER_ID,
        requested_institution_id=INSTITUTION_A,
        remembered_institution_id=INSTITUTION_B,
    )

    assert context is None
    assert stored is None


async def test_membership_unavailable_clears_context_but_keeps_remembered() -> None:
    """Вопрос 2 = А: без контекста, но запомненное значение не трогается."""
    memberships = FakeMemberships(error=MembershipCheckUnavailableError())

    context, stored = await resolve_institution_context(
        memberships,
        user_id=USER_ID,
        requested_institution_id=INSTITUTION_A,
        remembered_institution_id=INSTITUTION_B,
    )

    assert context is None
    assert stored == INSTITUTION_B


# --- refresh_session --------------------------------------------------------


async def test_refresh_session_rotated_returns_outcome() -> None:
    new_session = _session(institution_id=INSTITUTION_A)
    repo = FakeRepository(
        result=RotationResult(RotationOutcome.ROTATED, new_session, "new-raw-token"),
        rotate_calls=[],
    )
    memberships = FakeMemberships(role="teacher")

    outcome = await refresh_session(
        repo,
        memberships,
        session=_session(),
        token_hash="hash",
        requested_institution_id=INSTITUTION_A,
        idle_ttl=timedelta(days=7),
        reuse_grace=timedelta(seconds=30),
    )

    assert outcome.session is new_session
    assert outcome.raw_refresh_token == "new-raw-token"
    assert outcome.context == InstitutionContext(
        institution_id=INSTITUTION_A, role="teacher"
    )
    assert repo.rotate_calls[0]["institution_id"] == INSTITUTION_A


async def test_refresh_session_reused_raises() -> None:
    repo = FakeRepository(
        result=RotationResult(
            RotationOutcome.REUSED, _session(revoked_at=datetime.now(UTC))
        ),
        rotate_calls=[],
    )
    memberships = FakeMemberships()

    with pytest.raises(RefreshRejectedError):
        await refresh_session(
            repo,
            memberships,
            session=_session(),
            token_hash="hash",
            requested_institution_id=None,
            idle_ttl=timedelta(days=7),
            reuse_grace=timedelta(seconds=30),
        )


def test_rotation_result_repr_does_not_leak_raw_token() -> None:
    """I1, ревью Ч3: сырой токен не должен попадать в лог/трейсбек через
    дефолтный ``repr`` датакласса."""
    result = RotationResult(RotationOutcome.ROTATED, _session(), "super-secret-token")

    assert "super-secret-token" not in repr(result)


def test_refresh_outcome_repr_does_not_leak_raw_token() -> None:
    """I1, ревью Ч3: то же самое для результата use case."""
    outcome = RefreshOutcome(
        session=_session(), raw_refresh_token="super-secret-token", context=None
    )

    assert "super-secret-token" not in repr(outcome)


async def test_refresh_session_not_found_raises() -> None:
    repo = FakeRepository(
        result=RotationResult(RotationOutcome.NOT_FOUND), rotate_calls=[]
    )
    memberships = FakeMemberships()

    with pytest.raises(RefreshRejectedError):
        await refresh_session(
            repo,
            memberships,
            session=_session(),
            token_hash="hash",
            requested_institution_id=None,
            idle_ttl=timedelta(days=7),
            reuse_grace=timedelta(seconds=30),
        )
