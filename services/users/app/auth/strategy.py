"""JWT-стратегия сервиса users с прикладными claims."""

import logging
import math
import uuid
from datetime import UTC, datetime

from fastapi_users import exceptions
from fastapi_users.authentication import JWTStrategy
from fastapi_users.jwt import generate_jwt
from fastapi_users.manager import BaseUserManager
from gamification_auth import TokenError, decode_access_token
from pydantic import SecretStr

from app.auth.user_protocol import AppUserProtocol
from app.business.domain.entities import InstitutionContext
from app.business.use_cases.token_claims import build_token_claims
from app.repositories.denylist import TokenDenylist

logger = logging.getLogger(__name__)


class ClaimsJWTStrategy(JWTStrategy[AppUserProtocol, uuid.UUID]):
    """Стратегия с прикладными claims и строгой проверкой токена.

    От базовой отличается тремя вещами: составом полезной нагрузки; тем,
    что проверка идёт через общую библиотеку ``gamification_auth``, а не
    через библиотечный ``decode_jwt``; и тем, что токен можно отозвать —
    базовая на ``destroy_token`` отвечает отказом «JWT нельзя погасить».
    """

    def __init__(
        self, *args: object, denylist: TokenDenylist, **kwargs: object
    ) -> None:
        """Принять denylist сверх параметров базовой стратегии.

        Аргумент обязателен и именованный: стратегия без denylist — это
        сервис, у которого ``logout`` ничего не делает, и такую сборку
        не должно быть возможно получить по невнимательности.
        """
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._denylist = denylist

    async def write_token(
        self,
        user: AppUserProtocol,
        context: InstitutionContext | None = None,
        lifetime_seconds: int | None = None,
    ) -> str:
        """Выпустить токен доступа с прикладными claims.

        Значение ``context`` по умолчанию обязательно: библиотечный
        роутер логина вызывает ``write_token(user)``, и именно этот
        вызов обязан давать токен **без контекста учреждения**. Контекст
        появляется только при внутреннем выпуске токена в контексте
        (``POST /internal/tokens/institution-context``), куда его
        приносит gamification.

        ``lifetime_seconds`` по умолчанию ``None`` — полный настроенный
        срок. Явное значение передаёт только внутренний выпуск в
        контексте, чтобы новый токен наследовал остаток жизни
        предъявленного gamification ``subject_token``: refresh на этом
        этапе нет, и перевыпуск в контексте не должен превращаться в
        бесконечное продление сессии. Умолчание не трогать — логин
        обязан выдавать полный срок.
        """
        # ``aud`` берётся только из ``self.token_audience`` (список строк,
        # а не строка) и не подменяется: проверка валидирует аудиторию, и
        # любое расхождение выпуска с проверкой даст молчаливый 401 на
        # всех защищённых эндпоинтах.
        #
        # ``jti`` уникален для каждого выпущенного токена, поэтому он
        # рождается здесь, а не в ``build_token_claims``: та обязана
        # оставаться чистой функцией от пользователя. Нужен он отзыву —
        # denylist адресует токены по ``jti``, а не по всему их телу,
        # иначе нельзя погасить сессию целиком.
        #
        # Порядок распаковки важен: ``build_token_claims`` не возвращает
        # ни ``sub``, ни ``aud``, ни ``jti``, поэтому служебные поля не
        # затираются прикладными. Расширяя claims, инвариант сохранить.
        payload = {
            "sub": str(user.id),
            "aud": self.token_audience,
            "jti": str(uuid.uuid4()),
            **build_token_claims(user, context),
        }
        if lifetime_seconds is None:
            lifetime_seconds = self.lifetime_seconds
        return generate_jwt(
            payload, self.encode_key, lifetime_seconds, algorithm=self.algorithm
        )

    async def read_token(
        self,
        token: str | None,
        user_manager: BaseUserManager[AppUserProtocol, uuid.UUID],
    ) -> AppUserProtocol | None:
        """Проверить токен и поднять пользователя из хранилища.

        Библиотечная реализация переопределена, потому что её
        ``decode_jwt`` не умеет требовать обязательные claims: валидно
        подписанный токен **без ``exp``** она принимает бессрочно.
        Проверка вынесена в ``gamification_auth`` — тот же код, которым
        токен проверяют остальные сервисы, чтобы правила не разъехались.

        Пользователь поднимается из хранилища и после успешной проверки:
        внутри ``users`` источник истины — хранилище, а не claims, и
        деактивация учётки должна действовать немедленно.
        """
        if token is None:
            return None

        try:
            claims = decode_access_token(
                token,
                public_key=key_value(self.decode_key),
                algorithms=[self.algorithm],
                audience=self.token_audience,
            )
        except TokenError:
            # Причина отказа наружу не выносится: транспорт всё равно
            # отвечает 401, а подробности помогли бы подбирать токен.
            return None

        # Отзыв проверяется только после успешной проверки подписи:
        # спрашивать denylist о произвольной строке, поданной клиентом,
        # значит превращать его в бесплатную нагрузку извне.
        if claims.token_id is not None and await self._is_revoked(claims.token_id):
            return None

        try:
            return await user_manager.get(user_manager.parse_id(claims.subject))
        except (exceptions.UserNotExists, exceptions.InvalidID):
            return None

    async def destroy_token(self, token: str, user: AppUserProtocol) -> None:
        """Отозвать предъявленный токен до истечения его срока.

        Базовая реализация здесь поднимает
        ``StrategyDestroyNotSupportedError``; библиотечный
        ``AuthenticationBackend.logout`` эту ошибку глотает, поэтому до
        появления denylist выход из системы был вежливым 204 без
        последствий. Переопределение и делает его настоящим.

        Гасится **один** токен, а не все токены пользователя: ключ —
        ``jti``, уникальный для каждого выпуска. Вторая вкладка того же
        пользователя продолжает работать, и это осознанно — «выйти
        везде» потребовало бы серверных сессий, которых нет.

        TTL записи равен остатку жизни токена: дольше держать нечего,
        токен и так перестанет приниматься по ``exp``.
        """
        try:
            claims = decode_access_token(
                token,
                public_key=key_value(self.decode_key),
                algorithms=[self.algorithm],
                audience=self.token_audience,
            )
        except TokenError:
            # Невалидный или истёкший токен гасить нечего и незачем:
            # он и так не пройдёт проверку.
            return

        if claims.token_id is None:
            # Токен выпущен до введения ``jti``: поштучно он не
            # адресуется. Молчать нельзя — это конфигурационный дефект.
            logger.error("Cannot revoke a token without a jti claim")
            return

        ttl_seconds = math.ceil(
            (claims.expires_at - datetime.now(tz=UTC)).total_seconds()
        )
        try:
            await self._denylist.revoke(claims.token_id, ttl_seconds)
        except Exception:
            # Fail-open распространяется и на запись: выход из системы
            # не должен падать пятисоткой из-за недоступного denylist.
            # Токен доживёт свой срок — ущерб ограничен сверху остатком
            # TTL, и запись в лог обязана быть громкой.
            logger.exception("Token denylist is unavailable, token stays valid")

    async def _is_revoked(self, token_id: str) -> bool:
        """Спросить denylist об отзыве, пропуская токен при его отказе.

        **Fail-open — решение владельца проекта, а не упрощение.**
        Denylist недоступен рутинно и коротко: рестарт контейнера при
        передеплое, rolling update, drain узла. Ущерб от «пустить»
        ограничен сверху остатком TTL access (15 минут), тогда как
        fail-closed означал бы, что каждый рестарт хранилища кладёт всю
        школу целиком. Менять поведение на отказ нельзя.

        Уровень ``error`` обязателен: молчаливый fail-open неотличим от
        работающего отзыва, и дефект хранилища жил бы месяцами.
        """
        try:
            return await self._denylist.is_revoked(token_id)
        except Exception:
            logger.exception(
                "Token denylist is unavailable, accepting the token unchecked"
            )
            return False


def key_value(key: str | SecretStr) -> str:
    """Развернуть ключ проверки в строку.

    ``JWTStrategy`` допускает и ``str``, и ``SecretStr``; сервис передаёт
    второе, чтобы ошибочно поданный приватный ключ не попал в текст
    ошибки валидации настроек.
    """
    return key.get_secret_value() if isinstance(key, SecretStr) else key
