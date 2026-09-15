"""Корневой роутер HTTP API сервиса users.

Здесь собрана вся карта адресов сервиса: модули маршрутов объявляют
голый ``APIRouter()``, а ``prefix`` и ``tags`` задаются в месте
подключения. Карта должна читаться из одного файла, а не собираться по
крупицам из модулей.

Раскладка (см. ``.claude/knowledge/07-routing.md``):

* ``/users/...`` — внешнее API, единственное, что публикуется наружу:
  публичный префикс ``/api/v1/users/`` отображается шлюзом именно сюда.
  Аутентификация встроена внутрь того же префикса, отдельного корня
  ``/auth`` у сервиса нет.
* ``/internal/...`` — вызовы от других сервисов. Лежит вне ``/users``,
  поэтому недостижимо снаружи по построению, а не по запрету в nginx.
* ``/health`` — пробы оркестратора. Тоже вне ``/users``: их опрашивают
  Docker и k8s напрямую по порту сервиса.
"""

from fastapi import APIRouter

from app.api.external.v1.auth import router as auth_router
from app.api.external.v1.health import router as health_router
from app.api.internal.internal_router import router as internal_router
from app.auth.users import fastapi_users
from app.schemas.user import UserCreate, UserRead, UserUpdate

api_router = APIRouter()

# Health-пробы остаются вне аутентификации: их опрашивают Docker и k8s.
api_router.include_router(health_router, tags=["health"])

# Внутреннее API скрыто из публичной схемы: наружу оно не публикуется,
# и в OpenAPI для клиентов ему делать нечего.
api_router.include_router(internal_router, prefix="/internal", include_in_schema=False)

# Всё внешнее API сервиса — под одним префиксом, включая аутентификацию.
# Зависимости аутентификации на этот роутер вешать НЕЛЬЗЯ: под ним лежат
# и защищённые маршруты (``/users/me``), и заведомо публичные — вход и
# регистрация. Общие проверки навешиваются на вложенные роутеры.
users_router = APIRouter(prefix="/users")
users_router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate), tags=["users"]
)
users_router.include_router(auth_router, prefix="/auth/jwt", tags=["auth"])
users_router.include_router(
    fastapi_users.get_register_router(UserRead, UserCreate),
    prefix="/auth",
    tags=["auth"],
)
api_router.include_router(users_router)

# get_verify_router и get_reset_password_router намеренно не подключаются:
# верификация email и сброс пароля отложены вместе с почтовым сервисом.
# При их подключении в UserManager нужно задать verification_token_secret
# и reset_password_token_secret.
