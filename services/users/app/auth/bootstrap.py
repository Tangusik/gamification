"""Сид учётной записи администратора инсталляции."""

import logging

from fastapi_users.password import PasswordHelper

from app.repositories.protocols import UserRepository

logger = logging.getLogger(__name__)


async def seed_bootstrap_admin(
    user_db: UserRepository, email: str, password: str
) -> None:
    """Создать учётку оператора инсталляции, если её ещё нет.

    Операция идемпотентна: повторный запуск сервиса с теми же
    настройками не приводит ни к ошибке, ни к дублю.

    Учётке выставляется ``is_superuser`` — технический флаг владельца
    инсталляции. Роли ей не выдаётся и членства не создаётся: роль
    принадлежит паре «пользователь ↔ учреждение», а владелец инсталляции
    не состоит ни в одном учреждении. Ролевые проверки он проходит по
    ``is_superuser``, а его токен приходит без контекста учреждения — по
    отсутствию claim ``role`` соседние сервисы и отличают его от
    администратора учреждения.

    Ни пароль, ни email в логи не попадают.
    """
    existing = await user_db.get_by_email(email)
    if existing is not None:
        logger.debug("Bootstrap admin already exists, seeding skipped")
        return

    await user_db.create(
        {
            "email": email,
            "hashed_password": PasswordHelper().hash(password),
            "is_active": True,
            "is_verified": True,
            "is_superuser": True,
        }
    )
    logger.info("Bootstrap admin created")
