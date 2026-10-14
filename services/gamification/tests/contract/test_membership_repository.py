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


async def test_profile_name_is_saved_and_read_back(repos) -> None:
    """Профильное имя (план 11, этап 2) сохраняется и читается обеими
    реализациями — отдельно от ``display_name`` (накладки админа)."""
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    membership = _new_membership(
        institution_id=institution_id, profile_name="Профильное Имя"
    )
    await membership_repo.add(membership)

    fetched = await membership_repo.get_for_user(membership.user_id)
    assert fetched.profile_name == "Профильное Имя"
    assert fetched.display_name is None
    assert fetched.effective_name == "Профильное Имя"


async def test_set_profile_name_updates_only_this_user_across_institutions(
    user_memberships_repos,
) -> None:
    """Межарендная операция (план 11, этап 3): обновляет ``profile_name``
    во всех учреждениях указанного пользователя и не задевает чужие
    членства в тех же учреждениях; возвращает число обновлённых строк.
    """
    institution_repo, membership_repo_for, user_memberships = user_memberships_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    user_id = uuid.uuid4()
    stranger_id = uuid.uuid4()

    membership_repo_a = await membership_repo_for(institution_a)
    await membership_repo_a.add(
        _new_membership(user_id=user_id, institution_id=institution_a)
    )
    membership_repo_b = await membership_repo_for(institution_b)
    await membership_repo_b.add(
        _new_membership(user_id=user_id, institution_id=institution_b)
    )
    membership_repo_b = await membership_repo_for(institution_b)
    await membership_repo_b.add(
        _new_membership(user_id=stranger_id, institution_id=institution_b)
    )

    updated = await user_memberships.set_profile_name(user_id, "Новое Имя")

    assert updated == 2
    membership_repo_a = await membership_repo_for(institution_a)
    membership_repo_b = await membership_repo_for(institution_b)
    assert (await membership_repo_a.get_for_user(user_id)).profile_name == ("Новое Имя")
    assert (await membership_repo_b.get_for_user(user_id)).profile_name == ("Новое Имя")
    assert (await membership_repo_b.get_for_user(stranger_id)).profile_name is None


async def test_set_profile_name_for_unknown_user_updates_nothing(
    user_memberships_repos,
) -> None:
    institution_repo, membership_repo_for, user_memberships = user_memberships_repos
    await _seed_institution(institution_repo)

    updated = await user_memberships.set_profile_name(uuid.uuid4(), "Кто-то")

    assert updated == 0


async def test_set_profile_name_with_none_resets_name(user_memberships_repos) -> None:
    institution_repo, membership_repo_for, user_memberships = user_memberships_repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    membership = _new_membership(
        institution_id=institution_id, profile_name="Старое Имя"
    )
    await membership_repo.add(membership)

    updated = await user_memberships.set_profile_name(membership.user_id, None)

    assert updated == 1
    membership_repo = await membership_repo_for(institution_id)
    fetched = await membership_repo.get_for_user(membership.user_id)
    assert fetched.profile_name is None


async def test_update_preserves_profile_name_set_at_creation(repos) -> None:
    """``update`` пишет ``profile_name`` membership'а как есть (раздел 9
    плана 11) — здесь он не меняется, в отличие от ``display_name``."""
    institution_repo, membership_repo_for = repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    membership = _new_membership(
        institution_id=institution_id, profile_name="Профильное Имя"
    )
    await membership_repo.add(membership)

    membership.display_name = "Накладка"
    await membership_repo.update(membership)

    fetched = await membership_repo.get_for_user(membership.user_id)
    assert fetched.profile_name == "Профильное Имя"
    assert fetched.display_name == "Накладка"
    assert fetched.effective_name == "Накладка"
