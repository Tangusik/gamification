"""Контрактные тесты репозитория групп: обе реализации (раздел 7, Ч2б)."""

import uuid
from datetime import UTC, datetime

import pytest

from app.business.domain.entities import Group, Institution, Membership
from app.business.domain.enums import InstitutionKind, MembershipStatus, UserRole
from app.business.domain.errors import GroupNameTakenError


def _new_group(**overrides: object) -> Group:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        name="Кружок робототехники",
        created_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return Group(**defaults)  # type: ignore[arg-type]


def _new_membership(**overrides: object) -> Membership:
    defaults: dict[str, object] = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        institution_id=uuid.uuid4(),
        role=UserRole.TEACHER,
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


@pytest.fixture(params=["in_memory", pytest.param("postgres", marks=pytest.mark.db)])
async def group_repos(request: pytest.FixtureRequest):
    """``(institution_repo, membership_repo_for, group_repo_for)`` (H1).

    Обе фабрики асинхронны в обоих вариантах: под ``[postgres]`` они
    выставляют ``app.institution_id`` перед тем, как отдать репозиторий
    (У3-У5 плана 07a) — без этого ``FORCE ROW LEVEL SECURITY`` даёт 0
    строк на чтении таблиц ``memberships``/``groups`` и их связей.
    """
    if request.param == "in_memory":
        from app.repositories.in_memory import (
            InMemoryGroupRepository,
            InMemoryInstitutionMemberships,
            InMemoryInstitutionRepository,
            InMemoryStore,
        )

        store = InMemoryStore()
        institution_repo = InMemoryInstitutionRepository(store)

        async def membership_repo_for(institution_id):
            return InMemoryInstitutionMemberships(store, institution_id)

        async def group_repo_for(institution_id):
            return InMemoryGroupRepository(store, institution_id)

        yield institution_repo, membership_repo_for, group_repo_for
        return

    from app.repositories.database import create_session_factory
    from app.repositories.sql_alchemy import (
        SqlAlchemyGroupRepository,
        SqlAlchemyInstitutionMemberships,
        SqlAlchemyInstitutionRepository,
    )
    from tests.contract.conftest import postgres_schema, require_test_database_url
    from tests.db.conftest import set_institution_context

    async with postgres_schema(require_test_database_url()) as engine:
        async with create_session_factory(engine)() as session:
            institution_repo = SqlAlchemyInstitutionRepository(session)

            async def membership_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyInstitutionMemberships(session, institution_id)

            async def group_repo_for(institution_id):
                await set_institution_context(session, institution_id)
                return SqlAlchemyGroupRepository(session, institution_id)

            yield institution_repo, membership_repo_for, group_repo_for


async def test_add_then_get_returns_the_group(group_repos) -> None:
    institution_repo, _, group_repo_for = group_repos
    institution_id = await _seed_institution(institution_repo)
    group_repo = await group_repo_for(institution_id)
    group = _new_group(institution_id=institution_id)

    await group_repo.add(group)
    fetched = await group_repo.get(group.id)

    assert fetched is not None
    assert fetched.name == group.name


async def test_group_name_unique_case_insensitive_within_institution(
    group_repos,
) -> None:
    institution_repo, _, group_repo_for = group_repos
    institution_id = await _seed_institution(institution_repo)
    group_repo = await group_repo_for(institution_id)
    await group_repo.add(_new_group(institution_id=institution_id, name="Кружок"))

    with pytest.raises(GroupNameTakenError):
        await group_repo.add(_new_group(institution_id=institution_id, name="кружок"))


async def test_same_name_allowed_in_different_institutions(group_repos) -> None:
    institution_repo, _, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)

    await (await group_repo_for(institution_a)).add(
        _new_group(institution_id=institution_a, name="Кружок")
    )
    await (await group_repo_for(institution_b)).add(
        _new_group(institution_id=institution_b, name="Кружок")
    )

    assert len(await (await group_repo_for(institution_a)).list_all()) == 1
    assert len(await (await group_repo_for(institution_b)).list_all()) == 1


async def test_get_does_not_see_other_institution(group_repos) -> None:
    institution_repo, _, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    group = _new_group(institution_id=institution_a)
    await (await group_repo_for(institution_a)).add(group)

    assert await (await group_repo_for(institution_b)).get(group.id) is None


async def test_delete_returns_false_for_missing_group(group_repos) -> None:
    institution_repo, _, group_repo_for = group_repos
    institution_id = await _seed_institution(institution_repo)

    assert await (await group_repo_for(institution_id)).delete(uuid.uuid4()) is False


async def test_add_and_remove_teacher_is_idempotent_and_reflected_in_listing(
    group_repos,
) -> None:
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    teacher = _new_membership(institution_id=institution_id, role=UserRole.TEACHER)
    await membership_repo.add(teacher)
    group_repo = await group_repo_for(institution_id)
    group = _new_group(institution_id=institution_id)
    await group_repo.add(group)

    await group_repo.add_teacher(group_id=group.id, membership_id=teacher.id)
    await group_repo.add_teacher(group_id=group.id, membership_id=teacher.id)

    assert await group_repo.list_teacher_user_ids(group.id) == [teacher.user_id]

    await group_repo.remove_teacher(group_id=group.id, membership_id=teacher.id)
    await group_repo.remove_teacher(group_id=group.id, membership_id=teacher.id)

    assert await group_repo.list_teacher_user_ids(group.id) == []


async def test_student_can_belong_to_several_groups(group_repos) -> None:
    """В5/G2: связь ученик-группа не ограничена одной парой."""
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_id = await _seed_institution(institution_repo)
    membership_repo = await membership_repo_for(institution_id)
    student = _new_membership(institution_id=institution_id, role=UserRole.STUDENT)
    await membership_repo.add(student)
    group_repo = await group_repo_for(institution_id)
    group_a = _new_group(institution_id=institution_id, name="А")
    group_b = _new_group(institution_id=institution_id, name="Б")
    await group_repo.add(group_a)
    await group_repo.add(group_b)

    await group_repo.add_student(group_id=group_a.id, membership_id=student.id)
    await group_repo.add_student(group_id=group_b.id, membership_id=student.id)

    group_ids = await group_repo.list_group_ids_for_student(student.id)
    assert sorted(group_ids) == sorted([group_a.id, group_b.id])
    assert await group_repo.count_students(group_a.id) == 1
    assert await group_repo.count_students(group_b.id) == 1


async def test_repository_of_other_institution_does_not_see_teacher_link(
    group_repos,
) -> None:
    """H1: репозиторий учреждения A не видит связей группы учреждения B."""
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    membership_repo_b = await membership_repo_for(institution_b)
    teacher_b = _new_membership(institution_id=institution_b, role=UserRole.TEACHER)
    await membership_repo_b.add(teacher_b)
    group_repo_b = await group_repo_for(institution_b)
    group_b = _new_group(institution_id=institution_b)
    await group_repo_b.add(group_b)
    await group_repo_b.add_teacher(group_id=group_b.id, membership_id=teacher_b.id)

    foreign_repo = await group_repo_for(institution_a)
    assert await foreign_repo.list_teacher_user_ids(group_b.id) == []
    assert await foreign_repo.list_group_ids_for_teacher(teacher_b.id) == []


async def test_repository_of_other_institution_does_not_see_student_count(
    group_repos,
) -> None:
    """H1: репозиторий учреждения A не видит счётчика группы учреждения B."""
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    membership_repo_b = await membership_repo_for(institution_b)
    student_b = _new_membership(institution_id=institution_b, role=UserRole.STUDENT)
    await membership_repo_b.add(student_b)
    group_repo_b = await group_repo_for(institution_b)
    group_b = _new_group(institution_id=institution_b)
    await group_repo_b.add(group_b)
    await group_repo_b.add_student(group_id=group_b.id, membership_id=student_b.id)

    foreign_repo = await group_repo_for(institution_a)
    assert await foreign_repo.count_students(group_b.id) == 0
    assert await foreign_repo.list_group_ids_for_student(student_b.id) == []


async def test_repository_of_other_institution_does_not_attach_to_foreign_group(
    group_repos,
) -> None:
    """H1: репозиторий A не вставляет связь с группой B, даже имея своё членство."""
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    membership_repo_a = await membership_repo_for(institution_a)
    teacher_a = _new_membership(institution_id=institution_a, role=UserRole.TEACHER)
    await membership_repo_a.add(teacher_a)
    group_repo_b = await group_repo_for(institution_b)
    group_b = _new_group(institution_id=institution_b)
    await group_repo_b.add(group_b)

    group_repo_a = await group_repo_for(institution_a)
    await group_repo_a.add_teacher(group_id=group_b.id, membership_id=teacher_a.id)

    # Контекст сейчас — институт A (последней его выставила фабрика для
    # ``group_repo_a`` выше); под RLS ``group_repo_b`` без повторного
    # вызова фабрики читал бы уже не свои строки, а строки из чужого
    # контекста, и пустой результат ничего не доказывал бы (В4/P2 плана
    # 07a). Фабрика вызывается заново, чтобы вернуть контекст к B.
    assert (
        await (await group_repo_for(institution_b)).list_teacher_user_ids(group_b.id)
        == []
    )


async def test_repository_of_other_institution_does_not_attach_foreign_membership(
    group_repos,
) -> None:
    """H1: репозиторий A не вставляет связь с членством B, даже имея свою группу."""
    institution_repo, membership_repo_for, group_repo_for = group_repos
    institution_a = await _seed_institution(institution_repo)
    institution_b = await _seed_institution(institution_repo)
    membership_repo_b = await membership_repo_for(institution_b)
    teacher_b = _new_membership(institution_id=institution_b, role=UserRole.TEACHER)
    await membership_repo_b.add(teacher_b)
    group_repo_a = await group_repo_for(institution_a)
    group_a = _new_group(institution_id=institution_a)
    await group_repo_a.add(group_a)

    await group_repo_a.add_teacher(group_id=group_a.id, membership_id=teacher_b.id)

    assert await group_repo_a.list_teacher_user_ids(group_a.id) == []
