"""Контрактные тесты репозитория членств: изоляция арендатора (H1)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.entities import Institution, Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import MembershipAlreadyExistsError


def _new_membership(**overrides: object) -> Membership:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        role=UserRole.STUDENT,
        status=MembershipStatus.ACTIVE,
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Membership(**defaults)  # type: ignore[arg-type]


async def _seed_institution(institution_repo) -> uuid.UUID:
    institution = Institution(
        id=uuid.uuid4(),
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
    )
    await institution_repo.add(institution)
    return institution.id


async def test_add_then_get_for_user(repos) -> None:
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    user_id = uuid.uuid4()

    await membership_repo.add(
        _new_membership(user_id=user_id, institution_id=institution_id)
    )
    fetched = await membership_repo.get_for_user(user_id)

    assert fetched is not None
    assert fetched.user_id == user_id
    assert fetched.role is UserRole.STUDENT


async def test_get_for_user_missing_membership_returns_none(repos) -> None:
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)

    assert (
        await (await membership_repo_for(institution_id)).get_for_user(uuid.uuid4())
        is None
    )


async def test_duplicate_membership_is_rejected(repos) -> None:
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    user_id = uuid.uuid4()
    await membership_repo.add(
        _new_membership(user_id=user_id, institution_id=institution_id)
    )

    with pytest.raises(MembershipAlreadyExistsError):
        await membership_repo.add(
            _new_membership(user_id=user_id, institution_id=institution_id)
        )


async def test_get_for_user_does_not_see_other_institution(repos) -> None:
    """H1: без фильтра по арендатору метода не существует по построению."""
    institution_repo, membership_repo_for = repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    user_id = uuid.uuid4()
    await (await membership_repo_for(institution_a)).add(
        _new_membership(user_id=user_id, institution_id=institution_a)
    )

    assert (
        await (await membership_repo_for(institution_b)).get_for_user(user_id) is None
    )


async def test_list_by_role_returns_only_matching_role_in_this_institution(
    repos,
) -> None:
    institution_repo, membership_repo_for = repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    membership_repo_a = await membership_repo_for(institution_a)
    await membership_repo_a.add(
        _new_membership(role=UserRole.TEACHER, institution_id=institution_a)
    )
    await membership_repo_a.add(
        _new_membership(role=UserRole.STUDENT, institution_id=institution_a)
    )
    await (await membership_repo_for(institution_b)).add(
        _new_membership(role=UserRole.TEACHER, institution_id=institution_b)
    )

    # Контекст сейчас — институт B (его выставил вызов фабрики строкой
    # выше); под RLS чтение с уже полученным ``membership_repo_a`` без
    # повторного вызова фабрики видело бы строки B, а не A, и совпадение
    # с ожидаемым результатом было бы случайным (В4/P2 плана 07a).
    membership_repo_a = await membership_repo_for(institution_a)
    teachers = await membership_repo_a.list_by_role(UserRole.TEACHER)

    assert len(teachers) == 1
    assert teachers[0].role is UserRole.TEACHER


async def test_update_changes_display_name_and_status(repos) -> None:
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    membership = _new_membership(institution_id=institution_id)
    await membership_repo.add(membership)

    membership.display_name = "Имя"
    membership.status = MembershipStatus.SUSPENDED
    await membership_repo.update(membership)

    fetched = await membership_repo.get_for_user(membership.user_id)
    assert fetched.display_name == "Имя"
    assert fetched.status is MembershipStatus.SUSPENDED
