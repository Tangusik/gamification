"""Контрактные тесты репозитория приглашений: изоляция арендатора (H1)."""

import uuid
from datetime import UTC, datetime

from app.business.domain.entities import Institution, Invitation
from app.business.domain.enums import InstitutionKind, UserRole


def _new_invitation(**overrides: object) -> Invitation:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        token=f"token-{uuid.uuid4()}",
        role=UserRole.STUDENT,
        max_uses=1,
        uses_count=0,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
        revoked_at=None,
    )
    defaults.update(overrides)
    return Invitation(**defaults)  # type: ignore[arg-type]


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


async def test_add_then_get(invitation_repos) -> None:
    institution_repo, invitation_repo_for, _ = invitation_repos
    institution_id = await _seed_institution(institution_repo)
    invitation_repo = await invitation_repo_for(institution_id)
    invitation = _new_invitation(institution_id=institution_id)

    await invitation_repo.add(invitation)
    fetched = await invitation_repo.get(invitation.id)

    assert fetched is not None
    assert fetched.token == invitation.token
    assert fetched.max_uses == 1
    assert fetched.uses_count == 0
    assert fetched.revoked_at is None


async def test_get_does_not_see_other_institution(invitation_repos) -> None:
    """H1: без фильтра по арендатору метода не существует по построению."""
    institution_repo, invitation_repo_for, _ = invitation_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    invitation = _new_invitation(institution_id=institution_a)
    await (await invitation_repo_for(institution_a)).add(invitation)

    assert await (await invitation_repo_for(institution_b)).get(invitation.id) is None


async def test_list_all_scoped_to_institution(invitation_repos) -> None:
    institution_repo, invitation_repo_for, _ = invitation_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    invitation_a = _new_invitation(institution_id=institution_a)
    invitation_b = _new_invitation(institution_id=institution_b)
    await (await invitation_repo_for(institution_a)).add(invitation_a)
    await (await invitation_repo_for(institution_b)).add(invitation_b)

    listed = await (await invitation_repo_for(institution_a)).list_all()

    assert [item.id for item in listed] == [invitation_a.id]


async def test_revoke_is_idempotent(invitation_repos) -> None:
    institution_repo, invitation_repo_for, _ = invitation_repos
    institution_id = await _seed_institution(institution_repo)
    invitation_repo = await invitation_repo_for(institution_id)
    invitation = _new_invitation(institution_id=institution_id)
    await invitation_repo.add(invitation)

    await invitation_repo.revoke(invitation.id)
    first_revoked_at = (await invitation_repo.get(invitation.id)).revoked_at
    await invitation_repo.revoke(invitation.id)
    second_revoked_at = (await invitation_repo.get(invitation.id)).revoked_at

    assert first_revoked_at is not None
    assert first_revoked_at == second_revoked_at


async def test_revoke_missing_in_this_institution_does_nothing(
    invitation_repos,
) -> None:
    institution_repo, invitation_repo_for, _ = invitation_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    invitation = _new_invitation(institution_id=institution_a)
    await (await invitation_repo_for(institution_a)).add(invitation)

    await (await invitation_repo_for(institution_b)).revoke(invitation.id)

    fetched = await (await invitation_repo_for(institution_a)).get(invitation.id)
    assert fetched is not None
    assert fetched.revoked_at is None


async def test_lookup_finds_by_token_across_institutions(invitation_repos) -> None:
    institution_repo, invitation_repo_for, lookup = invitation_repos
    institution_id = await _seed_institution(institution_repo)
    invitation = _new_invitation(institution_id=institution_id)
    await (await invitation_repo_for(institution_id)).add(invitation)

    found = await lookup.get_for_accept(invitation.token)

    assert found is not None
    assert found.id == invitation.id


async def test_lookup_missing_token_returns_none(invitation_repos) -> None:
    _institution_repo, _invitation_repo_for, lookup = invitation_repos

    assert await lookup.get_for_accept("no-such-token") is None


async def test_lookup_increment_uses(invitation_repos) -> None:
    institution_repo, invitation_repo_for, lookup = invitation_repos
    institution_id = await _seed_institution(institution_repo)
    invitation = _new_invitation(institution_id=institution_id, max_uses=5)
    await (await invitation_repo_for(institution_id)).add(invitation)

    await lookup.increment_uses(invitation.id)
    await lookup.increment_uses(invitation.id)

    fetched = await (await invitation_repo_for(institution_id)).get(invitation.id)
    assert fetched is not None
    assert fetched.uses_count == 2
