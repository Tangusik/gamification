"""Доменные сущности членства (план 11, этап 2): правило отображения имени."""

import uuid
from datetime import UTC, datetime

from app.business.domain.entities import Invitation, Membership, create_institution
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole

NOW = datetime.now(UTC)


def _new_membership(**overrides: object) -> Membership:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        created_at=NOW,
    )
    defaults.update(overrides)
    return Membership(**defaults)  # type: ignore[arg-type]


def test_effective_name_prefers_display_name_override() -> None:
    membership = _new_membership(display_name="Накладка", profile_name="Профиль")
    assert membership.effective_name == "Накладка"


def test_effective_name_falls_back_to_profile_name() -> None:
    membership = _new_membership(display_name=None, profile_name="Профиль")
    assert membership.effective_name == "Профиль"


def test_effective_name_is_none_when_both_are_empty() -> None:
    membership = _new_membership(display_name=None, profile_name=None)
    assert membership.effective_name is None


def test_create_institution_sets_profile_name_on_admin_membership() -> None:
    created_by = uuid.uuid4()
    result = create_institution(
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=created_by,
        now=NOW,
        profile_name="Профильное Имя",
    )
    assert result.admin_membership.profile_name == "Профильное Имя"
    assert result.admin_membership.display_name is None
    assert result.admin_membership.effective_name == "Профильное Имя"


def test_create_institution_without_profile_name_leaves_it_empty() -> None:
    result = create_institution(
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=uuid.uuid4(),
        now=NOW,
    )
    assert result.admin_membership.profile_name is None
    assert result.admin_membership.effective_name is None


def _new_invitation(**overrides: object) -> Invitation:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        token="token",
        role=UserRole.STUDENT,
        max_uses=1,
        uses_count=0,
        created_by=uuid.uuid4(),
        created_at=NOW,
        revoked_at=None,
    )
    defaults.update(overrides)
    return Invitation(**defaults)  # type: ignore[arg-type]


def test_invitation_accept_sets_profile_name_on_new_membership() -> None:
    invitation = _new_invitation()
    membership = invitation.accept(
        user_id=uuid.uuid4(), now=NOW, profile_name="Профильное Имя"
    )
    assert membership.profile_name == "Профильное Имя"
    assert membership.display_name is None
    assert membership.effective_name == "Профильное Имя"


def test_invitation_accept_without_profile_name_leaves_it_empty() -> None:
    invitation = _new_invitation()
    membership = invitation.accept(user_id=uuid.uuid4(), now=NOW)
    assert membership.profile_name is None
    assert membership.effective_name is None
