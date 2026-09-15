"""Тесты эндпоинтов login/refresh/logout (план 10-refresh, раздел 3).

Готовность Ч1: ротация, повтор (гасит сессию), гонка двух refresh одним
токеном, окно 30 с, несовпадение ``client``, CSRF, logout уже
использованным токеном, смена пароля, недоступность/404 gamification,
``Cache-Control: no-store``, атрибуты cookie, отсутствие сырого токена в
логах.
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response

from app.api.deps import get_memberships_client
from app.business.domain.errors import (
    MembershipCheckUnavailableError,
    MembershipNotActiveError,
)
from app.core.config import MIN_PASSWORD_LENGTH, get_settings

EMAIL = "refresh-flow@example.com"
PASSWORD = "correct-horse-battery-staple"
SHORT_PASSWORD = "x" * (MIN_PASSWORD_LENGTH - 1)

CSRF_HEADERS = {"X-Requested-With": "gamification-web"}
MOBILE_HEADERS = {"X-Client": "mobile"}

Register = Callable[..., Awaitable[Response]]
Login = Callable[..., Awaitable[Response]]


class FakeMemberships:
    """Двойник gamification-клиента, управляемый тестом.

    ``on_resolve`` — необязательный хук, срабатывающий внутри вызова
    (до ответа): используется, чтобы эмулировать конкурентный запрос,
    успевающий изменить состояние сессии, пока refresh «ждёт» ответ
    gamification (L1, ревью Ч3).
    """

    def __init__(self, on_resolve: Callable[[], None] | None = None) -> None:
        self.role: str | None = None
        self.error: Exception | None = None
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []
        self.on_resolve = on_resolve

    async def resolve_role(
        self, *, user_id: uuid.UUID, institution_id: uuid.UUID
    ) -> str:
        self.calls.append((user_id, institution_id))
        if self.on_resolve is not None:
            self.on_resolve()
        if self.error is not None:
            raise self.error
        assert self.role is not None
        return self.role


@pytest.fixture
def fake_memberships(app: FastAPI) -> FakeMemberships:
    """Подменить клиент gamification фейком на время одного теста."""
    fake = FakeMemberships()
    app.dependency_overrides[get_memberships_client] = lambda: fake
    return fake


async def _login_web(client: AsyncClient, register: Register) -> Response:
    await register(EMAIL, PASSWORD)
    return await client.post(
        "/users/auth/jwt/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers=CSRF_HEADERS,
    )


async def _login_mobile(client: AsyncClient, register: Register) -> Response:
    await register(EMAIL, PASSWORD)
    return await client.post(
        "/users/auth/jwt/login",
        data={"username": EMAIL, "password": PASSWORD},
        headers=MOBILE_HEADERS,
    )


# --- login -------------------------------------------------------------


async def test_login_web_sets_cookie_and_omits_refresh_token_from_body(
    client: AsyncClient, register: Register
) -> None:
    response = await _login_web(client, register)

    assert response.status_code == 200, response.text
    assert "refresh_token" not in response.json()
    assert response.headers["Cache-Control"] == "no-store"
    assert "gamification_refresh" in response.cookies


async def test_login_mobile_returns_refresh_token_and_sets_no_cookie(
    client: AsyncClient, register: Register
) -> None:
    response = await _login_mobile(client, register)

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["refresh_token"], str) and body["refresh_token"]
    assert "gamification_refresh" not in response.cookies


async def test_login_without_headers_creates_no_session(
    client: AsyncClient, register: Register
) -> None:
    """К1: клиент без ``X-Client`` и без ``X-Requested-With`` (старая
    вкладка веба, старый APK) не получает cookie и не заводит
    refresh-сессию — иначе он не смог бы её погасить при выходе."""
    await register(EMAIL, PASSWORD)
    response = await client.post(
        "/users/auth/jwt/login", data={"username": EMAIL, "password": PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert set(response.json()) == {"access_token", "token_type"}
    assert "gamification_refresh" not in response.cookies

    # Сессия не заведена: у клиента нет cookie, а раз refresh-токен ему
    # тоже не выдан, следующий refresh невозможен в принципе — это и
    # есть подтверждение отсутствия сессии со стороны контракта API.
    refresh = await client.post("/users/auth/jwt/refresh", headers=CSRF_HEADERS)
    assert refresh.status_code == 401
    assert refresh.json() == {"detail": "REFRESH_TOKEN_INVALID"}


async def test_login_with_csrf_header_sets_cookie(
    client: AsyncClient, register: Register
) -> None:
    """К1: заголовок ``X-Requested-With`` — признак веб-клиента,
    который умеет погасить cookie при выходе."""
    response = await _login_web(client, register)

    assert response.status_code == 200, response.text
    assert "gamification_refresh" in response.cookies


async def test_refresh_cookie_attributes(
    client: AsyncClient, register: Register
) -> None:
    response = await _login_web(client, register)

    set_cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie
    assert (
        "SameSite=strict" in set_cookie.lower()
        or "samesite=strict" in set_cookie.lower()
    )
    assert "Path=/users/auth/jwt" in set_cookie


# --- refresh: базовая ротация -------------------------------------------


async def test_refresh_web_rotates_cookie_and_returns_access_token(
    client: AsyncClient, register: Register
) -> None:
    await _login_web(client, register)

    response = await client.post("/users/auth/jwt/refresh", headers=CSRF_HEADERS)

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert isinstance(response.json()["access_token"], str)
    assert "refresh_token" not in response.json()
    assert "gamification_refresh" in response.cookies


async def test_refresh_mobile_rotates_body_token(
    client: AsyncClient, register: Register
) -> None:
    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )

    assert response.status_code == 200, response.text
    new_refresh_token = response.json()["refresh_token"]
    assert new_refresh_token != old_refresh_token


async def test_old_token_after_rotation_is_rejected(
    client: AsyncClient, register: Register
) -> None:
    """Ротация: предыдущий токен больше не годится сам по себе."""
    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]
    await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )

    # Второй запрос тем же старым токеном — сразу за пределами окна
    # повтора он не проходил бы. Здесь же используем совсем другой
    # (заведомо мёртвый после первой успешной ротации) токен только
    # для проверки прямого отказа - см. тесты на grace/reuse ниже для
    # временной развилки.
    stale = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": "not-the-issued-token"},
        headers=MOBILE_HEADERS,
    )
    assert stale.status_code == 401
    assert stale.json() == {"detail": "REFRESH_TOKEN_INVALID"}
    assert stale.headers["Cache-Control"] == "no-store"


# --- reuse: grace и повтор -----------------------------------------------


async def test_reuse_within_grace_window_still_succeeds(
    client: AsyncClient, register: Register
) -> None:
    """Вопрос 3 = А: повтор в течение окна проворачивает ротацию ещё раз."""
    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]

    first = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert first.status_code == 200, first.text

    second = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )

    assert second.status_code == 200, second.text
    assert second.json()["refresh_token"] != first.json()["refresh_token"]


async def test_reuse_outside_grace_window_revokes_session(
    client: AsyncClient,
    register: Register,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повтор вне окна гасит всю сессию — оба токена перестают работать."""
    monkeypatch.setenv("USERS_REFRESH_REUSE_GRACE_SECONDS", "1")
    get_settings.cache_clear()

    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]

    first = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert first.status_code == 200, first.text
    new_refresh_token = first.json()["refresh_token"]

    await asyncio.sleep(1.2)

    reused = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert reused.status_code == 401
    assert reused.json() == {"detail": "REFRESH_TOKEN_INVALID"}

    # Сессия погашена целиком: токен, честно выданный первой ротацией,
    # тоже больше не работает.
    survivor_attempt = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": new_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert survivor_attempt.status_code == 401

    get_settings.cache_clear()


async def test_two_concurrent_refresh_calls_with_same_token(
    client: AsyncClient, register: Register
) -> None:
    """Гонка двух refresh одним токеном (H1, ревью Ч3, решение владельца
    2026-09-15): обе стороны получают доступ (grace покрывает и честную
    гонку — У3), но выживает только один токен цепочки. Токен
    проигравшей стороны предъявлять небезопасно: он больше не
    «неизвестен», а помечен использованным без своего преемника — его
    предъявление уходит в ветку повтора и гасит всю сессию целиком,
    включая токен выигравшей стороны. Это цена риска 1 плана (гонка
    вкладок без Web Locks), принятая владельцем."""
    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]

    async def _call() -> Response:
        return await client.post(
            "/users/auth/jwt/refresh",
            json={"refresh_token": old_refresh_token},
            headers=MOBILE_HEADERS,
        )

    first, second = await asyncio.gather(_call(), _call())

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    first_new = first.json()["refresh_token"]
    second_new = second.json()["refresh_token"]
    assert first_new != second_new

    async def _probe(token: str) -> Response:
        return await client.post(
            "/users/auth/jwt/refresh",
            json={"refresh_token": token},
            headers=MOBILE_HEADERS,
        )

    probe_first = await _probe(first_new)
    probe_second = await _probe(second_new)

    # Ровно один из двух кандидатов оказывается вытесненным преемником:
    # его предъявление гасит сессию (REUSED), а не просто получает 401
    # неизвестного токена.
    statuses = (probe_first.status_code, probe_second.status_code)
    assert statuses.count(401) >= 1

    # Если один из кандидатов успел продолжить цепочку до того, как
    # был предъявлен вытесненный, то после гашения сессии его новый
    # токен тоже больше не работает — сессия погашена целиком.
    survivor_token: str | None = None
    if probe_first.status_code == 200:
        survivor_token = probe_first.json()["refresh_token"]
    elif probe_second.status_code == 200:
        survivor_token = probe_second.json()["refresh_token"]

    if survivor_token is not None:
        dead = await _probe(survivor_token)
        assert dead.status_code == 401


async def test_stolen_token_reused_within_grace_then_evicted_successor_revokes_session(
    client: AsyncClient, register: Register
) -> None:
    """H1, ревью Ч3: вор предъявляет украденный T0 в окне после честной
    ротации. Преемник T1 не удаляется, а лишь помечается использованным
    — когда его предъявит легитимный пользователь, срабатывает ветка
    повтора и гасит всю сессию целиком, включая токен вора (T2)."""
    login_response = await _login_mobile(client, register)
    t0 = login_response.json()["refresh_token"]

    legit = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": t0},
        headers=MOBILE_HEADERS,
    )
    assert legit.status_code == 200, legit.text
    t1 = legit.json()["refresh_token"]

    thief = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": t0},
        headers=MOBILE_HEADERS,
    )
    assert thief.status_code == 200, thief.text
    t2 = thief.json()["refresh_token"]

    # Легитимный пользователь предъявляет T1, не подозревая о краже:
    # сессия гасится целиком, а не тихим 401 неизвестного токена.
    legit_again = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": t1},
        headers=MOBILE_HEADERS,
    )
    assert legit_again.status_code == 401
    assert legit_again.json() == {"detail": "REFRESH_TOKEN_INVALID"}

    # Токен вора (T2) тоже перестаёт работать.
    thief_again = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": t2},
        headers=MOBILE_HEADERS,
    )
    assert thief_again.status_code == 401


# --- client mismatch и CSRF ----------------------------------------------


async def test_mobile_token_rejected_on_web_path(
    client: AsyncClient, register: Register
) -> None:
    login_response = await _login_mobile(client, register)
    mobile_refresh_token = login_response.json()["refresh_token"]

    # Тело на web-сессии: заголовка X-Client нет, путь — web, но токен
    # передаётся телом, а не cookie — cookie не выставлена вовсе для
    # мобильной сессии, поэтому web-путь просто не находит токен.
    response = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": mobile_refresh_token},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "REFRESH_TOKEN_INVALID"}


async def test_refresh_without_csrf_header_is_rejected(
    client: AsyncClient, register: Register
) -> None:
    await _login_web(client, register)

    response = await client.post("/users/auth/jwt/refresh")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF_CHECK_FAILED"}


async def test_logout_without_csrf_header_is_rejected(
    client: AsyncClient, register: Register
) -> None:
    await _login_web(client, register)

    response = await client.post("/users/auth/jwt/logout")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF_CHECK_FAILED"}


# --- logout --------------------------------------------------------------


async def test_logout_with_already_used_refresh_token_still_succeeds(
    client: AsyncClient, register: Register
) -> None:
    """У10: logout гасит сессию по любому токену цепочки, даже использованному."""
    login_response = await _login_mobile(client, register)
    old_refresh_token = login_response.json()["refresh_token"]
    rotated = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert rotated.status_code == 200, rotated.text
    new_refresh_token = rotated.json()["refresh_token"]

    logout = await client.post(
        "/users/auth/jwt/logout",
        json={"refresh_token": old_refresh_token},
        headers=MOBILE_HEADERS,
    )

    assert logout.status_code == 204

    # Сессия погашена целиком — даже свежий токен больше не работает.
    stale = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": new_refresh_token},
        headers=MOBILE_HEADERS,
    )
    assert stale.status_code == 401


async def test_logout_with_bearer_only_revokes_access(
    client: AsyncClient, register: Register
) -> None:
    """К7: старый APK шлёт только ``Authorization``, без cookie и без
    ``X-Client`` — logout всё равно отзывает access (denylist), а не
    падает на CSRF, которого этому клиенту взять неоткуда."""
    await register(EMAIL, PASSWORD)
    login_response = await client.post(
        "/users/auth/jwt/login", data={"username": EMAIL, "password": PASSWORD}
    )
    access_token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    logout = await client.post("/users/auth/jwt/logout", headers=headers)
    assert logout.status_code == 204, logout.text

    me = await client.get("/users/me", headers=headers)
    assert me.status_code == 401


async def test_logout_without_cookie_does_not_clear_cookie(
    client: AsyncClient, register: Register
) -> None:
    """Регрессия К7: кросс-сайтовый POST без cookie не должен получать
    ``Set-Cookie`` на удаление ``gamification_refresh`` — иначе CSRF-форма
    без cookie стирает refresh-cookie жертвы, у которой cookie не пришла
    вместе с этим запросом (``SameSite=Strict``)."""
    response = await client.post("/users/auth/jwt/logout")

    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert "gamification_refresh" not in set_cookie


async def test_logout_clears_web_cookie(
    client: AsyncClient, register: Register
) -> None:
    await _login_web(client, register)

    response = await client.post("/users/auth/jwt/logout", headers=CSRF_HEADERS)

    assert response.status_code == 204
    set_cookie = response.headers.get("set-cookie", "")
    assert "gamification_refresh=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie.lower()


# --- смена пароля ----------------------------------------------------------


async def test_password_change_revokes_all_sessions(
    client: AsyncClient,
    register: Register,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    web_login = await _login_web(client, register)
    assert web_login.status_code == 200, web_login.text
    headers = await auth_headers(EMAIL, PASSWORD)

    patch = await client.patch(
        "/users/me", headers=headers, json={"password": "brand-new-password-123"}
    )
    assert patch.status_code == 200, patch.text

    refresh_after = await client.post("/users/auth/jwt/refresh", headers=CSRF_HEADERS)
    assert refresh_after.status_code == 401
    assert refresh_after.json() == {"detail": "REFRESH_TOKEN_INVALID"}


async def test_password_change_rejected_by_validation_keeps_sessions(
    client: AsyncClient,
    register: Register,
    auth_headers: Callable[..., Awaitable[dict[str, str]]],
) -> None:
    """L3, ревью Ч3: сессии гасятся до записи нового хеша, но после
    валидации пароля (решение владельца 2026-09-15). Отклонённый новый
    пароль — ошибка ввода, а не смена пароля: пользователя не выкидывает
    со всех устройств."""
    web_login = await _login_web(client, register)
    assert web_login.status_code == 200, web_login.text
    headers = await auth_headers(EMAIL, PASSWORD)

    patch = await client.patch(
        "/users/me", headers=headers, json={"password": SHORT_PASSWORD}
    )
    assert patch.status_code == 400, patch.text

    refresh_after = await client.post("/users/auth/jwt/refresh", headers=CSRF_HEADERS)
    assert refresh_after.status_code == 200, refresh_after.text


# --- gamification: недоступность и 404 ------------------------------------


async def test_gamification_unavailable_gives_access_without_context(
    client: AsyncClient, register: Register, fake_memberships: FakeMemberships
) -> None:
    fake_memberships.error = MembershipCheckUnavailableError()
    login_response = await _login_mobile(client, register)
    refresh_token = login_response.json()["refresh_token"]
    institution_id = uuid.uuid4()

    response = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": refresh_token, "institution_id": str(institution_id)},
        headers=MOBILE_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert fake_memberships.calls == [(fake_memberships.calls[0][0], institution_id)]


async def test_gamification_404_clears_remembered_institution(
    client: AsyncClient, register: Register, fake_memberships: FakeMemberships
) -> None:
    fake_memberships.role = "teacher"
    login_response = await _login_mobile(client, register)
    refresh_token = login_response.json()["refresh_token"]
    institution_id = uuid.uuid4()

    first = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": refresh_token, "institution_id": str(institution_id)},
        headers=MOBILE_HEADERS,
    )
    assert first.status_code == 200, first.text
    second_refresh_token = first.json()["refresh_token"]

    fake_memberships.role = None
    fake_memberships.error = MembershipNotActiveError()

    second = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": second_refresh_token},
        headers=MOBILE_HEADERS,
    )

    assert second.status_code == 200, second.text


# --- L1: устаревшее состояние между find и rotate --------------------------


async def test_session_revoked_during_gamification_call_rejects_refresh(
    client: AsyncClient, register: Register, app: FastAPI
) -> None:
    """L1, ревью Ч3 (эмуляция для in-memory): если сессию гасит
    конкурентный запрос, пока refresh ждёт ответ gamification, ротация
    обязана увидеть отзыв и отказать, а не выдать access по устаревшему
    состоянию.

    На in-memory адаптере этот путь и так корректен (нет отдельной
    identity map поверх БД) — тест фиксирует контракт use case на
    уровне сквозного вызова. Сам дефект SQL-хранилища (устаревание
    ``Session.get`` без ``populate_existing``) закрыт прямым тестом
    против PostgreSQL — см. ``tests/db/test_refresh_session_repository_db.py``.
    """
    login_response = await _login_mobile(client, register)
    refresh_token = login_response.json()["refresh_token"]

    def _revoke_concurrently() -> None:
        store = app.state.refresh_session_storage
        for session in store.sessions.values():
            session.revoked_at = datetime.now(UTC)
            session.revoke_reason = "logout"

    fake = FakeMemberships(on_resolve=_revoke_concurrently)
    fake.role = "teacher"
    app.dependency_overrides[get_memberships_client] = lambda: fake

    response = await client.post(
        "/users/auth/jwt/refresh",
        json={"refresh_token": refresh_token, "institution_id": str(uuid.uuid4())},
        headers=MOBILE_HEADERS,
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "REFRESH_TOKEN_INVALID"}


# --- логи ------------------------------------------------------------------


async def test_raw_refresh_token_never_logged(
    client: AsyncClient, register: Register, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    login_response = await _login_mobile(client, register)
    refresh_token = login_response.json()["refresh_token"]

    with caplog.at_level(logging.DEBUG):
        response = await client.post(
            "/users/auth/jwt/refresh",
            json={"refresh_token": refresh_token},
            headers=MOBILE_HEADERS,
        )

    assert response.status_code == 200, response.text
    new_refresh_token = response.json()["refresh_token"]
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert refresh_token not in log_text
    assert new_refresh_token not in log_text
