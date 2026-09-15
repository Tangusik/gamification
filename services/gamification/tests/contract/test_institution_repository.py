"""Контрактные тесты репозитория учреждений: обе реализации (раздел 7)."""

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from app.business.domain.entities import Institution
from app.business.domain.enums import InstitutionKind


def _new_institution(**overrides: object) -> Institution:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        name="Школа №1",
        kind=InstitutionKind.SCHOOL,
        created_by=uuid.uuid4(),
        created_at=datetime.now(UTC),
        currency_name=None,
    )
    defaults.update(overrides)
    return Institution(**defaults)  # type: ignore[arg-type]


async def test_add_then_get_returns_the_institution(repos) -> None:
    institution_repo, _ = repos
    institution = _new_institution()

    await institution_repo.add(institution)
    fetched = await institution_repo.get(institution.id)

    assert fetched is not None
    assert fetched.id == institution.id
    assert fetched.name == institution.name
    assert fetched.kind is institution.kind
    assert fetched.created_by == institution.created_by
    assert fetched.currency_name is None


async def test_get_missing_institution_returns_none(repos) -> None:
    institution_repo, _ = repos

    assert await institution_repo.get(uuid.uuid4()) is None


async def test_add_then_get_returns_currency_name(repos) -> None:
    institution_repo, _ = repos
    institution = _new_institution(currency_name="монетки")

    await institution_repo.add(institution)
    fetched = await institution_repo.get(institution.id)

    assert fetched is not None
    assert fetched.currency_name == "монетки"


async def test_update_changes_name_and_currency_name(repos) -> None:
    institution_repo, _ = repos
    institution = _new_institution(currency_name="монетки")
    await institution_repo.add(institution)

    updated = replace(institution, name="Новое имя", currency_name="звёзды")
    await institution_repo.update(updated)
    fetched = await institution_repo.get(institution.id)

    assert fetched is not None
    assert fetched.name == "Новое имя"
    assert fetched.currency_name == "звёзды"


async def test_update_can_clear_currency_name(repos) -> None:
    institution_repo, _ = repos
    institution = _new_institution(currency_name="монетки")
    await institution_repo.add(institution)

    updated = replace(institution, currency_name=None)
    await institution_repo.update(updated)
    fetched = await institution_repo.get(institution.id)

    assert fetched is not None
    assert fetched.currency_name is None
