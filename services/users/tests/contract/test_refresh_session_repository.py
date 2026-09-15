"""Контрактные тесты хранилища refresh-сессий (план 10-refresh).

Тесты написаны против порта ``RefreshSessionRepository``
(``app.business.ports``) через фикстуру ``refresh_repo_and_user``: ни
конкретный класс, ни его внутреннее состояние здесь не упоминаются —
файл переносится на in-memory и PostgreSQL без изменений.
"""

import uuid
from datetime import timedelta

from app.business.domain.entities import RefreshSession, hash_refresh_token
from app.business.ports import RefreshSessionRepository, RotationOutcome

IDLE_TTL = timedelta(days=7)
ABSOLUTE_TTL = timedelta(days=30)
NO_GRACE = timedelta(seconds=0)
WITH_GRACE = timedelta(seconds=30)


async def _create_session(
    repo: RefreshSessionRepository, user_id: uuid.UUID, **overrides: object
) -> tuple[RefreshSession, str]:
    kwargs: dict[str, object] = {
        "user_id": user_id,
        "client": "web",
        "institution_id": None,
        "idle_ttl": IDLE_TTL,
        "absolute_ttl": ABSOLUTE_TTL,
    }
    kwargs.update(overrides)
    return await repo.create(**kwargs)  # type: ignore[arg-type]


async def test_create_returns_session_and_nonempty_raw_token(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user

    session, raw_token = await _create_session(repo, user_id)

    assert session.user_id == user_id
    assert session.client == "web"
    assert session.institution_id is None
    assert session.revoked_at is None
    assert isinstance(raw_token, str) and raw_token


async def test_find_unknown_token_returns_none(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, _user_id = refresh_repo_and_user

    assert await repo.find(hash_refresh_token("unknown-token")) is None


async def test_find_known_token_returns_its_session(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)

    found = await repo.find(hash_refresh_token(raw_token))

    assert found is not None
    assert found.id == session.id


async def test_rotate_unknown_token_returns_not_found(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, _user_id = refresh_repo_and_user

    result = await repo.rotate(
        token_hash=hash_refresh_token("unknown-token"),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )

    assert result.outcome is RotationOutcome.NOT_FOUND
    assert result.session is None
    assert result.raw_token is None


async def test_rotate_issues_new_token_and_retires_old_one(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    """Ротация выдаёт новый токен; старый больше не годится для ротации."""
    repo, user_id = refresh_repo_and_user
    institution_id = uuid.uuid4()
    session, raw_token = await _create_session(repo, user_id)
    old_hash = hash_refresh_token(raw_token)

    result = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=NO_GRACE,
        institution_id=institution_id,
    )

    assert result.outcome is RotationOutcome.ROTATED
    assert result.session is not None
    assert result.session.id == session.id
    assert result.session.institution_id == institution_id
    assert result.raw_token is not None
    assert result.raw_token != raw_token

    # Новый токен рабочий.
    new_session = await repo.find(hash_refresh_token(result.raw_token))
    assert new_session is not None
    assert new_session.id == session.id


async def test_rotate_reused_token_outside_grace_revokes_session(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    """Повтор без grace (У2, вопрос 3 = Б-ветка) гасит всю сессию."""
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)
    old_hash = hash_refresh_token(raw_token)

    first = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=NO_GRACE,
        institution_id=None,
    )
    assert first.outcome is RotationOutcome.ROTATED

    second = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=NO_GRACE,
        institution_id=None,
    )

    assert second.outcome is RotationOutcome.REUSED
    assert second.session is not None
    assert second.session.id == session.id
    assert second.session.revoked_at is not None
    assert second.session.revoke_reason == "reuse"

    # Токен, выданный первой ротацией, тоже мёртв — сессия погашена целиком.
    assert first.raw_token is not None
    survivor = await repo.rotate(
        token_hash=hash_refresh_token(first.raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=NO_GRACE,
        institution_id=None,
    )
    assert survivor.outcome is RotationOutcome.NOT_FOUND


async def test_rotate_reused_token_within_grace_reissues_and_marks_successor_used(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    """Grace-окно (вопрос 3 = А): повтор проворачивает ротацию ещё раз.

    Преемник первой ротации не удаляется (H1, ревью Ч3): он лишь
    помечается использованным без собственного преемника, поэтому его
    последующее предъявление уходит в ветку повтора и гасит сессию
    целиком — вместе с токеном, выигравшим гонку. Это цена, принятая
    владельцем (риск 1 плана: гонка вкладок без Web Locks).
    """
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)
    old_hash = hash_refresh_token(raw_token)

    first = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert first.outcome is RotationOutcome.ROTATED
    assert first.raw_token is not None

    second = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )

    assert second.outcome is RotationOutcome.ROTATED
    assert second.session is not None
    assert second.session.id == session.id
    assert second.session.revoked_at is None
    assert second.raw_token is not None
    assert second.raw_token != first.raw_token

    # Преемник первой ротации предъявлен: это настоящий повтор, а не
    # неизвестный токен, — сессия гасится целиком.
    reused_successor = await repo.rotate(
        token_hash=hash_refresh_token(first.raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert reused_successor.outcome is RotationOutcome.REUSED
    assert reused_successor.session is not None
    assert reused_successor.session.id == session.id
    assert reused_successor.session.revoked_at is not None
    assert reused_successor.session.revoke_reason == "reuse"

    # Токен, выигравший гонку (grace-ротация), тоже мёртв — сессия
    # погашена без исключений.
    also_dead = await repo.rotate(
        token_hash=hash_refresh_token(second.raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert also_dead.outcome is RotationOutcome.NOT_FOUND


async def test_rotate_revoked_session_returns_not_found(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)
    await repo.revoke(session.id, reason="logout")

    result = await repo.rotate(
        token_hash=hash_refresh_token(raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )

    assert result.outcome is RotationOutcome.NOT_FOUND


async def test_rotate_expired_session_returns_not_found(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user
    _session, raw_token = await _create_session(
        repo, user_id, absolute_ttl=timedelta(seconds=-1)
    )

    result = await repo.rotate(
        token_hash=hash_refresh_token(raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )

    assert result.outcome is RotationOutcome.NOT_FOUND


async def test_revoke_for_user_revokes_all_sessions(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user
    _first_session, first_raw = await _create_session(repo, user_id, client="web")
    _second_session, second_raw = await _create_session(repo, user_id, client="mobile")

    await repo.revoke_for_user(user_id, reason="password_change")

    for raw_token in (first_raw, second_raw):
        result = await repo.rotate(
            token_hash=hash_refresh_token(raw_token),
            idle_ttl=IDLE_TTL,
            reuse_grace=WITH_GRACE,
            institution_id=None,
        )
        assert result.outcome is RotationOutcome.NOT_FOUND


async def test_revoke_by_token_revokes_even_already_used_token(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    """У10: logout гасит сессию по любому токену цепочки, включая использованный."""
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)
    old_hash = hash_refresh_token(raw_token)
    rotated = await repo.rotate(
        token_hash=old_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert rotated.outcome is RotationOutcome.ROTATED

    # Гасим сессию по СТАРОМУ (уже использованному) токену.
    await repo.revoke_by_token(old_hash, reason="logout")

    assert rotated.raw_token is not None
    result = await repo.rotate(
        token_hash=hash_refresh_token(rotated.raw_token),
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert result.outcome is RotationOutcome.NOT_FOUND


async def test_delete_expired_for_user_removes_only_expired(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    repo, user_id = refresh_repo_and_user
    _expired_session, expired_raw = await _create_session(
        repo, user_id, absolute_ttl=timedelta(seconds=-1)
    )
    _alive_session, alive_raw = await _create_session(repo, user_id)

    await repo.delete_expired_for_user(user_id)

    assert await repo.find(hash_refresh_token(expired_raw)) is None
    assert await repo.find(hash_refresh_token(alive_raw)) is not None


async def test_release_after_find_does_not_break_further_rotation(
    refresh_repo_and_user: tuple[RefreshSessionRepository, uuid.UUID],
) -> None:
    """L2, ревью Ч3: ``release`` закрывает транзакцию чтения без побочных
    эффектов на дальнейшую работу с той же сессией."""
    repo, user_id = refresh_repo_and_user
    session, raw_token = await _create_session(repo, user_id)
    token_hash = hash_refresh_token(raw_token)

    found = await repo.find(token_hash)
    assert found is not None
    assert found.id == session.id

    await repo.release()

    result = await repo.rotate(
        token_hash=token_hash,
        idle_ttl=IDLE_TTL,
        reuse_grace=WITH_GRACE,
        institution_id=None,
    )
    assert result.outcome is RotationOutcome.ROTATED
