"""Прикладной менеджер пользователей поверх fastapi-users."""

import logging
import uuid

from fastapi import Request
from fastapi_users import BaseUserManager, InvalidPasswordException, UUIDIDMixin
from fastapi_users import exceptions as fastapi_users_exceptions

from app.auth.user_protocol import AppUserProtocol
from app.core.config import MIN_PASSWORD_LENGTH
from app.repositories.protocols import RefreshSessionRepository, UserRepository
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserManager(UUIDIDMixin, BaseUserManager[AppUserProtocol, uuid.UUID]):
    """Бизнес-логика операций над пользователями.

    ``parse_id`` приходит из ``UUIDIDMixin`` и не переопределяется.

    Инвариант регистрации: **самостоятельная регистрация не создаёт
    членства**, а значит не даёт доступа ни к одному учреждению. Роли у
    пользователя больше нет вовсе — она принадлежит членству, — поэтому
    нормализация роли при ``safe=True`` отсюда удалена: нормализовать
    нечего. Единственный путь выдачи роли теперь один — создание
    членства, и публичного API у него пока нет.

    Атрибуты ``reset_password_token_secret`` и
    ``verification_token_secret`` намеренно не заданы: они нужны только
    роутерам сброса пароля и верификации email, а те не подключаются на
    этом этапе (нет почтового сервиса). При их подключении сюда
    обязательно добавить оба секрета — иначе первый же запрос упадёт с
    ``AttributeError``, — и брать их из настроек, а не из литералов.

    ``refresh_sessions`` — опционален намеренно: менеджер используется и
    там, где refresh-сессии ни при чём (заведение аккаунта через
    ``POST /internal/users``), заводить там фиктивный репозиторий не за
    чем. Смена пароля гасит все refresh-сессии пользователя (вопрос 5,
    план 10-refresh) — только если репозиторий передан.
    """

    def __init__(
        self,
        user_db: UserRepository,
        refresh_sessions: RefreshSessionRepository | None = None,
    ) -> None:
        super().__init__(user_db)
        self._refresh_sessions = refresh_sessions

    async def validate_password(
        self, password: str, user: UserCreate | AppUserProtocol
    ) -> None:
        """Отвергнуть заведомо слабый пароль.

        Базовая реализация не проверяет ничего, поэтому без этого
        переопределения принимался пароль в один символ. Правило одно —
        минимальная длина; сложность и словарные проверки к задаче
        этапа не относятся.

        В текст ошибки попадает только требование: сам пароль ни в
        ответе, ни в логах появляться не должен.
        """
        if len(password) < MIN_PASSWORD_LENGTH:
            raise InvalidPasswordException(
                reason=(
                    "Password is too short: "
                    f"at least {MIN_PASSWORD_LENGTH} characters required"
                )
            )

    async def update(
        self,
        user_update: UserUpdate,
        user: AppUserProtocol,
        safe: bool = False,
        request: Request | None = None,
    ) -> AppUserProtocol:
        """Обновить пользователя; смена пароля снимает временный флаг.

        ``must_change_password`` — из ``_PROTECTED_FIELDS``, клиент не
        может снять его сам полем в теле запроса. Единственный законный
        способ — смена пароля тем же запросом (решение C1): проверяется
        по исходному ``user_update.password``, а не по вычищенному
        словарю, который до сущности вообще не доходит.

        Пока флаг стоит, новый пароль обязан отличаться от временного:
        иначе пользователь мог бы «сменить» пароль на тот же самый и
        снять флаг, не зная своего реального временного пароля. Старый
        хеш сохраняется до вызова ``super().update``, потому что
        SQL-репозиторий меняет тот же объект ``user`` через ``setattr``
        — после вызова в нём уже новый хеш.

        Флаг снимается тем же вызовом, чтобы ответ ``PATCH /users/me``
        уже содержал ``must_change_password: false`` — фронт обновляет
        ``user`` из этого ответа, второй запрос ему не нужен.

        Смена пароля гасит все refresh-сессии пользователя (вопрос 5):
        клиент, только что отправивший новый пароль, сам входит им
        заново. Гашение происходит **до** записи нового хеша (L3, ревью
        Ч3, решение владельца 2026-09-15): запись пароля и гашение сессий
        идут через разные репозитории с собственными коммитами, единой
        транзакции на двоих у них нет, а порядок «сперва хеш, потом
        гашение» оставлял окно, где упавшее между ними гашение держало
        сессии живыми уже при скомпрометированном пароле. Обратный
        порядок безопаснее: если запись пароля после этого упадёт (или
        не пройдёт валидацию), лишний выход из системы — цена, а не риск.
        """
        if user.must_change_password and user_update.password is not None:
            old_hashed_password = user.hashed_password
            is_same_password, _ = self.password_helper.verify_and_update(
                user_update.password, old_hashed_password
            )
            if is_same_password:
                raise InvalidPasswordException(
                    reason=("New password must differ from the temporary password")
                )
        if user_update.password is not None and self._refresh_sessions is not None:
            # Сначала валидация: иначе отклонённый новый пароль (например,
            # слишком короткий) всё равно выкидывал бы пользователя со всех
            # устройств. ``super().update`` проверит пароль ещё раз — это
            # дешёвая повторная проверка, а не второй источник правил.
            await self.validate_password(user_update.password, user)
            await self._refresh_sessions.revoke_for_user(
                user.id, reason="password_change"
            )
        updated_user = await super().update(
            user_update, user, safe=safe, request=request
        )
        if user_update.password is not None and updated_user.must_change_password:
            updated_user = await self.user_db.update(
                updated_user, {"must_change_password": False}
            )
        return updated_user

    async def create(
        self,
        user_create: UserCreate,
        safe: bool = False,
        request: Request | None = None,
        *,
        must_change_password: bool = False,
    ) -> AppUserProtocol:
        """Создать пользователя одной записью, при необходимости — с флагом.

        Повторяет тело ``BaseUserManager.create`` (валидация пароля,
        проверка занятого email, хеширование), а не вызывает его: нужно
        вложить ``must_change_password`` в тот же ``user_dict`` до
        единственного вызова ``user_db.create``. Внутреннее API заводило
        флаг вторым отдельным ``UPDATE`` после создания — между двумя
        записями аккаунт с временным паролем на мгновение существовал
        без флага. ``must_change_password=False`` по умолчанию не меняет
        поведение обычной саморегистрации.
        """
        await self.validate_password(user_create.password, user_create)

        existing_user = await self.user_db.get_by_email(user_create.email)
        if existing_user is not None:
            raise fastapi_users_exceptions.UserAlreadyExists()

        user_dict = (
            user_create.create_update_dict()
            if safe
            else user_create.create_update_dict_superuser()
        )
        password = user_dict.pop("password")
        user_dict["hashed_password"] = self.password_helper.hash(password)
        if must_change_password:
            user_dict["must_change_password"] = True

        created_user = await self.user_db.create(user_dict)

        await self.on_after_register(created_user, request)

        return created_user

    async def on_after_register(
        self, user: AppUserProtocol, request: Request | None = None
    ) -> None:
        """Залогировать факт регистрации.

        В лог идёт только идентификатор: ни email, ни пароль, ни токен
        в логах появляться не должны. Роли у зарегистрированного
        пользователя нет — членств у него ноль.
        """
        logger.info("User registered: user_id=%s", user.id)

    async def on_after_login(
        self,
        user: AppUserProtocol,
        request: Request | None = None,
        response: object | None = None,
    ) -> None:
        """Залогировать факт входа: только идентификатор пользователя."""
        logger.info("User logged in: user_id=%s", user.id)
