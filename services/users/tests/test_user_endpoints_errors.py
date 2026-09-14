"""Ошибочные пути эндпоинтов ``/users/*``, зафиксированные как контракт.

Счастливый путь живёт в ``test_auth_flow.py``, состав claims — в
``test_token_claims.py``. Здесь только отказы. Учреждения и членства
переехали в gamification вместе со своим словарём ошибок доступа.

Форма тела одна на весь сервис: ``{"detail": "СТРОКА"}``. Единственное
исключение — 422 от валидации FastAPI, где ``detail`` содержит список
полей с ошибками: схлопнуть его в строку значило бы потерять информацию
о том, какое поле неверно.
"""

import uuid
from collections.abc import Awaitable, Callable

from fastapi_users.jwt import generate_jwt
from httpx import AsyncClient, Response

from app.business.domain.entities import User
from app.core.config import get_settings

EMAIL = "errors@example.com"
OTHER_EMAIL = "errors-other@example.com"
PASSWORD = "correct-horse-battery-staple"
AUDIENCE = ["fastapi-users:auth"]
ALGORITHM = "RS256"

Register = Callable[..., Awaitable[Response]]
AuthHeaders = Callable[..., Awaitable[dict[str, str]]]
FindUser = Callable[[str], User]


def _bearer(token: str) -> dict[str, str]:
    """Собрать заголовок авторизации из готового токена."""
    return {"Authorization": f"Bearer {token}"}


async def test_me_without_authorization_header_is_unauthorized(
    client: AsyncClient,
) -> None:
    """Профиль без токена не отдаётся.

    Тело — строка, а не объект: форма ответа об ошибке одна на сервис.
    ``Unauthorized`` вместо машиночитаемого кода — известное расхождение
    контракта (вопрос ``AUTH_REQUIRED`` в открытых), поэтому фиксируется
    как есть: молча менять его нельзя.
    """
    response = await client.get("/users/me")

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_me_with_malformed_token_is_unauthorized(client: AsyncClient) -> None:
    """Строка, не являющаяся токеном вовсе, даёт 401, а не 500.

    Отличается от уже покрытых случаев чужой подписи и истёкшего срока:
    здесь токен не разбирается на структуру, и ошибка приходит из
    другого места разбора.
    """
    response = await client.get("/users/me", headers=_bearer("not.a.token"))

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_me_without_bearer_scheme_is_unauthorized(
    client: AsyncClient, get_token: Callable[..., Awaitable[str]]
) -> None:
    """Валидный токен без схемы ``Bearer`` не принимается."""
    token = await get_token(EMAIL, PASSWORD)

    response = await client.get("/users/me", headers={"Authorization": token})

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_token_of_unknown_user_is_unauthorized(client: AsyncClient) -> None:
    """Токен нашей подписи с чужим ``sub`` внутрь не пускает.

    Пользователь поднимается из хранилища и после успешной проверки
    подписи: внутри сервиса источник истины — хранилище, а не claims.
    """
    token = generate_jwt(
        {"sub": str(uuid.uuid4()), "aud": AUDIENCE, "jti": str(uuid.uuid4())},
        get_settings().jwt_private_key.get_secret_value(),
        900,
        algorithm=ALGORITHM,
    )

    response = await client.get("/users/me", headers=_bearer(token))

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_deactivated_account_is_unauthorized(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: FindUser
) -> None:
    """Деактивация учётки действует немедленно, не дожидаясь истечения токена.

    Токен остаётся валидным по подписи и сроку, но пользователь
    поднимается из хранилища на каждом запросе — поэтому доступ
    закрывается сразу.
    """
    headers = await auth_headers(EMAIL, PASSWORD)
    find_user(EMAIL).is_active = False

    response = await client.get("/users/me", headers=headers)

    assert response.status_code == 401
    assert response.json() == {"detail": "Unauthorized"}


async def test_get_user_by_id_forbidden_for_regular_user(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    """Чужой профиль по идентификатору доступен только владельцу инсталляции."""
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.get(f"/users/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


async def test_get_user_by_id_not_found_for_superuser(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: FindUser
) -> None:
    """Несуществующий идентификатор даёт 404 владельцу инсталляции."""
    headers = await auth_headers(EMAIL, PASSWORD)
    find_user(EMAIL).is_superuser = True

    response = await client.get(f"/users/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_malformed_user_id_is_not_found_for_superuser(
    client: AsyncClient, auth_headers: AuthHeaders, find_user: FindUser
) -> None:
    """Не-UUID в пути даёт 404, а не 422: библиотека принимает ``id`` строкой.

    Роутер fastapi-users объявляет параметр пути как ``str`` и разбирает
    его сам, сводя ``InvalidID`` к 404. Валидация FastAPI до этого не
    доходит, поэтому 422 здесь не бывает — поведение зафиксировано,
    чтобы смена версии библиотеки не сломала клиента молча.
    """
    headers = await auth_headers(EMAIL, PASSWORD)
    find_user(EMAIL).is_superuser = True

    response = await client.get("/users/not-a-uuid", headers=headers)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_malformed_user_id_is_forbidden_for_regular_user(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    """Обычному пользователю не-UUID даёт тот же 403, что и валидный чужой id.

    Проверка прав стоит раньше разбора пути, поэтому по коду ответа
    нельзя отличить существующий идентификатор от синтаксически
    неверного — пространство идентификаторов не прощупывается.
    """
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.get("/users/not-a-uuid", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


async def test_delete_user_forbidden_for_regular_user(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    """Удаление пользователя обычному аккаунту недоступно."""
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.delete(f"/users/{uuid.uuid4()}", headers=headers)

    assert response.status_code == 403
    assert response.json() == {"detail": "Forbidden"}


async def test_patch_me_with_wrong_field_type_lists_fields(
    client: AsyncClient, auth_headers: AuthHeaders
) -> None:
    """422 отдаёт список полей, а не строку кода — единственное исключение.

    Схлопывать это тело в код нельзя: форма на клиенте потеряет
    информацию о том, какое поле неверно.
    """
    headers = await auth_headers(EMAIL, PASSWORD)

    response = await client.patch("/users/me", json={"email": 5}, headers=headers)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["body", "email"]


async def test_patch_me_with_taken_email_returns_code(
    client: AsyncClient, auth_headers: AuthHeaders, register: Register
) -> None:
    """Смена email на занятый даёт код строкой, а не объект библиотеки.

    Без обработчика ``HTTPException`` в ``app/core/exceptions.py`` часть
    ответов fastapi-users приходила бы объектом
    ``{"code": ..., "reason": ...}``, и клиент разбирал бы два формата.
    """
    headers = await auth_headers(EMAIL, PASSWORD)
    await register(OTHER_EMAIL, PASSWORD)

    response = await client.patch(
        "/users/me", json={"email": OTHER_EMAIL}, headers=headers
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "UPDATE_USER_EMAIL_ALREADY_EXISTS"}


async def test_register_with_taken_email_returns_code(register: Register) -> None:
    """Повторная регистрация того же email отвергается кодом контракта."""
    await register(EMAIL, PASSWORD)

    response = await register(EMAIL, PASSWORD)

    assert response.status_code == 400
    assert response.json() == {"detail": "REGISTER_USER_ALREADY_EXISTS"}


async def test_register_with_malformed_email_lists_fields(
    register: Register,
) -> None:
    """Синтаксически неверный email — ошибка валидации со списком полей."""
    response = await register("not-an-email", PASSWORD)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"] == ["body", "email"]
