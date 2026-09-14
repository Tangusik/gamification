"""Точка входа fastapi-users: роутеры и зависимости текущего пользователя."""

import uuid

from fastapi_users import FastAPIUsers

from app.api.deps import get_user_manager
from app.auth.backend import auth_backend
from app.auth.user_protocol import AppUserProtocol

fastapi_users = FastAPIUsers[AppUserProtocol, uuid.UUID](
    get_user_manager, [auth_backend]
)

# Базовая зависимость аутентификации: 401 на отсутствующий или
# просроченный токен и на деактивированную учётку.
current_active_user = fastapi_users.current_user(active=True)

# Технический флаг владельца инсталляции, а не прикладная роль.
# Ролевые проверки — ответственность gamification: у users больше нет
# ни ролей, ни хранилища членств, по которому их можно бы было решать.
current_active_superuser = fastapi_users.current_user(active=True, superuser=True)
