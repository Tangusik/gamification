"""Сборка backend'а аутентификации: транспорт плюс стратегия."""

from typing import Annotated

from fastapi import Depends
from fastapi_users.authentication import AuthenticationBackend, BearerTransport

from app.api.deps import get_token_denylist
from app.auth.strategy import ClaimsJWTStrategy
from app.core.config import get_settings
from app.repositories.denylist import TokenDenylist

# tokenUrl обязан совпадать с местом монтирования роутера логина
# (`/users` + `/auth/jwt` + `/login` в app.api.main_router). Расхождение
# не ломает сам логин, но кнопка Authorize в Swagger UI начнёт бить не
# туда. Путь относительный: публичный префикс добавляет root_path.
bearer_transport = BearerTransport(tokenUrl="users/auth/jwt/login")


def build_jwt_strategy(denylist: TokenDenylist) -> ClaimsJWTStrategy:
    """Создать стратегию по текущим настройкам сервиса.

    Чистая сборка, отделённая от зависимости FastAPI: стратегия нужна и
    вне запроса — в тестах и в утилитах, — а тянуть туда механику
    ``Depends`` не за чем.

    Настройки читаются в момент вызова, а не на импорте модуля: иначе
    импорт любого модуля, тянущего backend, потребовал бы заданного
    окружения. Алгоритм и время жизни токена — параметры конфигурации,
    а не константы кода.
    """
    settings = get_settings()
    # secret и public_key — разные ключи пары: первым стратегия
    # подписывает, вторым проверяет. Приватный не должен покидать этот
    # сервис, публичный раздаётся остальным.
    return ClaimsJWTStrategy(
        secret=settings.jwt_private_key.get_secret_value(),
        public_key=settings.jwt_public_key,
        lifetime_seconds=settings.jwt_lifetime_seconds,
        algorithm=settings.jwt_algorithm,
        denylist=denylist,
    )


def get_jwt_strategy(
    denylist: Annotated[TokenDenylist, Depends(get_token_denylist)],
) -> ClaimsJWTStrategy:
    """Зависимость FastAPI, выдающая стратегию с подключённым denylist.

    ``AuthenticationBackend`` вызывает ``get_strategy`` как обычную
    зависимость, поэтому у неё можно объявить собственные ``Depends`` —
    denylist приходит сюда так же, как репозитории приходят в
    обработчики, и остаётся подменяемым в одной точке шва.
    """
    return build_jwt_strategy(denylist)


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)
