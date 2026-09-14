"""Протоколы бизнес-слоя: то, что реализует инфраструктура.

Направление зависимостей: ``business ← repositories / clients / auth ←
api ← main`` (раздел 2 плана). Домен объявляет контракты, инфраструктура
их реализует — обратное users, где протоколы жили на стороне хранилища.
"""

import uuid
from datetime import datetime
from typing import Protocol

from app.business.domain.entities import (
    CurrencyTransaction,
    Group,
    Institution,
    Invitation,
    Membership,
    Privilege,
    Purchase,
)
from app.business.domain.enums import PurchaseStatus, UserRole


class Clock(Protocol):
    """Единственная точка, откуда бизнес-слой берёт текущее время."""

    def now(self) -> datetime:
        """Вернуть текущий момент, осознанный по часовому поясу."""
        ...


class InstitutionRepository(Protocol):
    """Создание и чтение учреждений.

    Не арендованная операция: сам ресурс здесь — это арендатор, фильтр
    по ``institution_id`` для него бессмыслен.
    """

    async def add(self, institution: Institution) -> None:
        """Поставить учреждение в очередь на запись; коммитит UnitOfWork."""
        ...

    async def get(self, institution_id: uuid.UUID) -> Institution | None:
        """Вернуть учреждение по идентификатору или ``None``."""
        ...

    async def update(self, institution: Institution) -> None:
        """Записать изменяемые поля учреждения (Ч2г: только ``name``).

        ``kind`` и ``created_by`` не меняются этим этапом (В7/S1).
        """
        ...


class InstitutionMemberships(Protocol):
    """Членства **одного** учреждения — привязка задаётся при сборке (H1).

    Метода без фильтра по арендатору здесь нет и не может появиться:
    объект уже привязан к ``institution_id`` в момент создания
    (``UnitOfWork.for_institution``).
    """

    async def add(self, membership: Membership) -> None:
        """Поставить членство в очередь на запись; коммитит UnitOfWork.

        :raises MembershipAlreadyExistsError: у пользователя уже есть
            членство в этом учреждении.
        """
        ...

    async def get_for_user(self, user_id: uuid.UUID) -> Membership | None:
        """Вернуть членство пользователя в этом учреждении или ``None``."""
        ...

    async def get_by_id(self, membership_id: uuid.UUID) -> Membership | None:
        """Вернуть членство по его id в этом учреждении или ``None``.

        Нужен валюте (раздел «Ч1» плана 06): ``created_by_name`` и
        ``created_by_role`` в ответе берутся из членства автора на момент
        чтения, а не из снимка на момент записи.
        """
        ...

    async def list_by_role(self, role: UserRole) -> list[Membership]:
        """Вернуть все членства этого учреждения с заданной ролью (Ч2а/2в)."""
        ...

    async def update(self, membership: Membership) -> None:
        """Записать изменяемые поля членства (``display_name``, ``status``).

        Роль и идентификаторы не меняются — эндпоинты этого этапа их не
        трогают (раздел «Умолчания»: смена роли вне объёма).
        """
        ...


class GroupRepository(Protocol):
    """Группы **одного** учреждения — привязка задаётся при сборке (H1).

    У ученика может быть несколько групп (В5/G2, против рекомендации):
    связи «группа ↔ ученик» и «группа ↔ преподаватель» — многие-ко-многим
    без ограничения на одну пару, первичный ключ таблицы связи — сама
    пара.

    Методы, принимающие ``group_id``/``membership_id`` напрямую, сами
    проверяют принадлежность обоих этому учреждению (H1) — молча не
    делают ничего (вставка/удаление связи) или отдают пустой результат
    (чтение), если группа или членство относятся к другому учреждению.
    Use case'ы и так проверяют группу и члена до вызова — это защита
    интерфейса на случай прямого вызова с чужими id.
    """

    async def add(self, group: Group) -> None:
        """:raises GroupNameTakenError: имя занято без учёта регистра."""
        ...

    async def get(self, group_id: uuid.UUID) -> Group | None:
        """Вернуть группу этого учреждения по идентификатору или ``None``."""
        ...

    async def list_all(self) -> list[Group]:
        """Вернуть все группы учреждения."""
        ...

    async def rename(self, group_id: uuid.UUID, name: str) -> Group | None:
        """Переименовать группу; ``None`` — группы нет в этом учреждении.

        :raises GroupNameTakenError: новое имя занято другой группой.
        """
        ...

    async def delete(self, group_id: uuid.UUID) -> bool:
        """Удалить группу и её связи (``ON DELETE CASCADE``).

        Возвращает ``False``, если группы в этом учреждении не было —
        use case превращает это в ``GroupNotFoundError``.
        """
        ...

    async def add_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        """Прикрепить преподавателя к группе; идемпотентно."""
        ...

    async def remove_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        """Открепить преподавателя от группы; идемпотентно."""
        ...

    async def add_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        """Прикрепить ученика к группе; идемпотентно (В5/G2: групп может
        быть несколько)."""
        ...

    async def remove_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        """Открепить ученика от группы; идемпотентно."""
        ...

    async def list_teacher_user_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        """``user_id`` преподавателей группы, для ответа ``GroupRead``."""
        ...

    async def count_students(self, group_id: uuid.UUID) -> int:
        """Число учеников в группе, для ответа ``GroupRead``."""
        ...

    async def list_group_ids_for_teacher(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Группы, которые ведёт этот преподаватель."""
        ...

    async def list_group_ids_for_student(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Группы, в которых состоит этот ученик (В5/G2: может быть несколько)."""
        ...


class CurrencyRepository(Protocol):
    """Валюта **одного** учреждения — привязка задаётся при сборке (H1).

    Методов изменения и удаления записей нет (У4): история операций
    неизменяема по построению порта, а не только по дисциплине вызывающего
    кода. Второй слой неизменяемости — триггер БД на таблице.
    """

    async def record(self, transaction: CurrencyTransaction) -> None:
        """Записать операцию и обновить баланс упсертом (У2) одной
        транзакцией; коммитит UnitOfWork.

        :raises OperationIdConflictError: ``operation_id`` уже занят в
            этом учреждении другой операцией (гонка, SAVEPOINT).
        :raises TransactionAlreadyReversedError: гонка двух сторно одной
            записи — ``UNIQUE(reverses_id)`` отдало эту операцию другому
            запросу раньше.
        :raises InsufficientBalanceError: отрицательная сумма (сторно,
            план 07 В4/RV1) увела бы баланс ниже нуля — второй рубеж,
            ``CHECK (balance >= 0)``.
        """
        ...

    async def get(self, transaction_id: uuid.UUID) -> CurrencyTransaction | None:
        """Вернуть операцию этого учреждения по идентификатору или ``None``."""
        ...

    async def get_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> CurrencyTransaction | None:
        """Вернуть операцию этого учреждения по ``operation_id`` или ``None``.

        Пространство ``operation_id`` общее для начислений и сторно (В4/I1).
        """
        ...

    async def get_balance(self, membership_id: uuid.UUID) -> int:
        """Вернуть баланс ученика; нет строки — 0 (У2)."""
        ...

    async def list_balances(
        self, membership_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Вернуть балансы нескольких учеников одним запросом (риск 9: N+1).

        Отсутствующим в результате ``membership_id`` соответствует баланс 0.
        """
        ...

    async def list_transactions(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[CurrencyTransaction]:
        """Последние ``limit`` операций ученика, новые сверху (У1:
        ``created_at DESC, id DESC``)."""
        ...


class MarketRepository(Protocol):
    """Маркет привилегий **одного** учреждения — привязка задаётся при
    сборке (H1), как и у остальных репозиториев ``InstitutionScope``.

    Каталогом управляет только ``institution_admin`` (П2) — эта проверка
    делает use case, порт её не знает. Покупка, отказ и списание валюты
    идут в одной транзакции UnitOfWork (план 07, Ч1).
    """

    async def add_privilege(self, privilege: Privilege) -> None:
        """Поставить позицию каталога в очередь на запись."""
        ...

    async def get_privilege(self, privilege_id: uuid.UUID) -> Privilege | None:
        """Вернуть позицию этого учреждения по идентификатору или ``None``."""
        ...

    async def list_privileges(self, *, active_only: bool) -> list[Privilege]:
        """Каталог этого учреждения; ``active_only`` — скрыть ``is_active
        = False`` (student/teacher видят только активные, У3)."""
        ...

    async def update_privilege(self, privilege: Privilege) -> Privilege | None:
        """Записать изменённые поля позиции — какие менять, решил use case
        (У11). ``None`` — позиции нет в этом учреждении."""
        ...

    async def purchase(
        self,
        *,
        membership_id: uuid.UUID,
        privilege_id: uuid.UUID,
        expected_price: int,
        operation_id: uuid.UUID,
        created_at: datetime,
    ) -> Purchase:
        """Атомарная покупка: списать остаток позиции, затем баланс,
        затем записать историю и саму покупку — порядок блокировок
        «позиция → баланс» (план 07, риск 1).

        :raises PrivilegeNotFoundError: позиции нет, она из другого
            учреждения или скрыта (``is_active=False``).
        :raises OutOfStockError: позиция активна, но остаток исчерпан.
        :raises PriceChangedError: цена позиции изменилась (У5).
        :raises InsufficientBalanceError: баланса не хватает (П3).
        :raises OperationIdConflictError: ``operation_id`` уже занят —
            гонка, второй рубеж после проверки в use case.
        """
        ...

    async def get_purchase(self, purchase_id: uuid.UUID) -> Purchase | None:
        """Вернуть покупку этого учреждения по идентификатору или ``None``."""
        ...

    async def get_purchase_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> Purchase | None:
        """Вернуть покупку этого учреждения по ``operation_id`` или ``None``."""
        ...

    async def list_my_purchases(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[Purchase]:
        """Последние ``limit`` покупок ученика, новые сверху (У8)."""
        ...

    async def list_purchases(
        self,
        *,
        status: PurchaseStatus | None,
        membership_id: uuid.UUID | None,
        limit: int | None,
    ) -> list[Purchase]:
        """Покупки учреждения для админа: без фильтра и без ``pending``
        лимит есть, у ``pending`` — нет (У8). ``limit=None`` — без лимита.
        """
        ...

    async def resolve_fulfil(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
    ) -> Purchase:
        """Отметить покупку выданной; идемпотентно по статусу (У9).

        :raises PurchaseNotFoundError: покупки нет в этом учреждении.
        :raises PurchaseAlreadyResolvedError: покупка уже отклонена.
        """
        ...

    async def resolve_reject(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
        refund_operation_id: uuid.UUID,
    ) -> Purchase:
        """Отклонить покупку: вернуть валюту (``purchase_refund``) и
        остаток позиции; идемпотентно по статусу (У9, В2/M2).

        :raises PurchaseNotFoundError: покупки нет в этом учреждении.
        :raises PurchaseAlreadyResolvedError: покупка уже выдана.
        """
        ...


class InvitationRepository(Protocol):
    """Приглашения **одного** учреждения — привязка задаётся при сборке (H1).

    Метода поиска по токену здесь нет: он межарендный (см.
    ``InvitationLookup``) и выделен в отдельный порт намеренно.
    """

    async def add(self, invitation: Invitation) -> None:
        """Поставить приглашение в очередь на запись; коммитит UnitOfWork."""
        ...

    async def get(self, invitation_id: uuid.UUID) -> Invitation | None:
        """Вернуть приглашение этого учреждения по идентификатору или ``None``."""
        ...

    async def list_all(self) -> list[Invitation]:
        """Вернуть все приглашения учреждения (видимость — задача use case)."""
        ...

    async def revoke(self, invitation_id: uuid.UUID) -> None:
        """Отметить приглашение отозванным.

        Идемпотентно: повторный вызов на уже отозванном приглашении и
        вызов на несуществующем в этом учреждении идентификаторе не
        меняют ничего и не бросают исключение — решение о том, было ли
        приглашение видно вызывающему, принимает use case до вызова.
        """
        ...


class InstitutionScope(Protocol):
    """Репозитории, привязанные к конкретному учреждению (H1)."""

    memberships: InstitutionMemberships
    invitations: InvitationRepository
    groups: GroupRepository
    currency: CurrencyRepository
    market: MarketRepository


class UserMemberships(Protocol):
    """Межарендная операция: собственные членства пользователя (H1).

    Выделена в отдельный порт с явным именем — именно такие операции
    (по ``user_id``, без фильтра по учреждению) требуют осознанного
    решения, а не доступны по умолчанию.
    """

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        """Вернуть все членства пользователя во всех учреждениях."""
        ...


class InvitationLookup(Protocol):
    """Межарендная операция: поиск приглашения по токену при принятии (H1).

    Выделена отдельным портом с явным именем — как и ``UserMemberships``,
    это операция без фильтра по учреждению, доступная не всем.
    """

    async def get_for_accept(self, token: str) -> Invitation | None:
        """Найти приглашение по токену с блокировкой строки (``FOR UPDATE``).

        Блокировка нужна принятию: два параллельных запроса по одному
        одноразовому токену не должны оба увидеть ``uses_count = 0``.
        """
        ...

    async def increment_uses(self, invitation_id: uuid.UUID) -> None:
        """Увеличить счётчик применений на единицу."""
        ...


class UnitOfWork(Protocol):
    """Одна транзакция на use case; коммит один раз (раздел 7).

    Репозитории делают ``add``/``flush``, коммитит только
    ``UnitOfWork.commit()`` — если он не был вызван до выхода из
    ``async with``, изменения отменяются целиком.
    """

    institutions: InstitutionRepository
    user_memberships: UserMemberships
    invitation_lookup: InvitationLookup

    async def for_institution(self, institution_id: uuid.UUID) -> InstitutionScope:
        """Получить репозитории, привязанные к этому учреждению (H1).

        Реализация поверх PostgreSQL (В3/A1 плана 07a) заодно выставляет
        ``app.institution_id`` в текущей транзакции для политик RLS —
        отсюда ``async``. Повторный вызов в одном ``UnitOfWork`` с другим
        ``institution_id`` — ошибка использования (``RuntimeError``): один
        UoW обслуживает одно учреждение за транзакцию.
        """
        ...

    async def commit(self) -> None:
        """Зафиксировать все изменения, сделанные внутри транзакции."""
        ...

    async def __aenter__(self) -> "UnitOfWork": ...

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None: ...


class TokenIssuer(Protocol):
    """Порт внутреннего выпуска токена в контексте учреждения (раздел 4)."""

    async def issue_context_token(
        self, *, subject_token: str, institution_id: uuid.UUID, role: str
    ) -> str:
        """Обменять предъявленный токен на токен в контексте учреждения.

        :raises TokenIssuerUnavailableError: users недоступен, не ответил
            вовремя или отверг служебный секрет вызывающего.
        :raises SubjectTokenRejectedError: users отверг ``subject_token``.
        :raises TokenIssuerContractError: users ответил не по контракту.
        """
        ...


class UserAccounts(Protocol):
    """Порт создания аккаунтов в users (В1/А1, раздел «Ч2» плана)."""

    async def create_account(self, *, email: str, password: str) -> uuid.UUID:
        """Завести аккаунт в users и вернуть его ``user_id``.

        :raises EmailAlreadyRegisteredError: email уже занят (В2/B3).
        :raises InvalidPasswordError: users отверг пароль.
        :raises UsersUnavailableError: users недоступен, не ответил
            вовремя или отверг служебный секрет вызывающего.
        :raises UsersContractError: users ответил не по контракту.
        """
        ...
