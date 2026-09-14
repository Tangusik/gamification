"""Тесты политики паролей: регистрация и пароль bootstrap-админа."""

from collections.abc import Awaitable, Callable

import pytest
from httpx import Response

from app.core.config import MIN_PASSWORD_LENGTH, InsecureSettingError, Settings

Register = Callable[..., Awaitable[Response]]

SHORT_PASSWORD = "x" * (MIN_PASSWORD_LENGTH - 1)


async def test_register_rejects_short_password(register: Register) -> None:
    """Короткий пароль при регистрации отвергается роутером.

    Без ``UserManager.validate_password`` принимался пароль в один
    символ, поэтому проверка идёт именно по коду ответа контракта
    fastapi-users.

    Тело — строка кода, хотя библиотека отдаёт здесь объект
    ``{"code": ..., "reason": ...}``: ответы приводятся к единой форме
    (см. ``app/core/exceptions.py``).
    """
    response = await register("short-password@example.com", SHORT_PASSWORD)

    assert response.status_code == 400, response.text
    assert response.json() == {"detail": "REGISTER_INVALID_PASSWORD"}


def test_settings_reject_short_bootstrap_admin_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Короткий пароль админа инсталляции не проходит валидацию настроек.

    Сид пишет напрямую в репозиторий, минуя ``UserManager``, поэтому
    единственное место проверки этого пароля — настройки. Значение
    пароля в текст ошибки попадать не должно.

    ``_env_file=None`` отключает чтение ``.env`` рядом с сервисом:
    результат теста не должен зависеть от окружения разработчика.
    """
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_PASSWORD", SHORT_PASSWORD)

    with pytest.raises(InsecureSettingError) as error:
        Settings(_env_file=None)

    message = str(error.value)
    assert "Bootstrap admin password is too short" in message
    assert SHORT_PASSWORD not in message


def test_settings_accept_blank_bootstrap_admin_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Пустой пароль админа означает «сида нет», а не «пароль короткий».

    Так его передаёт compose: переменная объявлена всегда, и незаданное
    значение приезжает пустой строкой. Регрессия ронять старт сервиса
    здесь не должна — при пустом значении сид просто не выполняется
    (``app/main.py``).
    """
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_PASSWORD", "")

    settings = Settings(_env_file=None)

    assert settings.bootstrap_admin_password is None
