"""Адаптеры бизнес-портов поверх PostgreSQL.

Общий принцип — как в ``services/users/app/repositories/sql_alchemy.py``:
нарушение уникальности приходит из БД (SAVEPOINT + разбор SQLSTATE), а
не проверяется предварительным ``SELECT`` — тот не защищает от гонки.

Репозитории делают ``add``/``flush`` и не коммитят сами: коммит — дело
``UnitOfWork`` (``app/repositories/uow.py``), вызывается один раз на
use case (раздел 7).
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import case, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.business.domain.entities import (
    CurrencyTransaction,
    Group,
    Institution,
    Invitation,
    Membership,
    Privilege,
    Purchase,
)
from app.business.domain.enums import PurchaseStatus, TransactionKind, UserRole
from app.business.domain.errors import (
    DomainError,
    GroupNameTakenError,
    InsufficientBalanceError,
    MemberNotFoundError,
    MembershipAlreadyExistsError,
    OperationIdConflictError,
    OutOfStockError,
    PriceChangedError,
    PrivilegeNotFoundError,
    PurchaseAlreadyResolvedError,
    PurchaseNotFoundError,
    TransactionAlreadyReversedError,
    TransactionNotFoundError,
)
from app.repositories.models import (
    CurrencyBalanceModel,
    CurrencyTransactionModel,
    GroupModel,
    GroupStudentModel,
    GroupTeacherModel,
    InstitutionModel,
    InvitationModel,
    MembershipModel,
    PrivilegeModel,
    PurchaseModel,
)

# Имя ограничения ``UNIQUE(reverses_id)`` по naming convention проекта
# (``app/repositories/database.py``) — отличает гонку двух сторно одной
# записи от обычного конфликта ``operation_id``.
CURRENCY_REVERSES_ID_UNIQUE_CONSTRAINT = "uq_currency_transactions_reverses_id"

# SQLSTATE нарушения уникального ограничения в PostgreSQL.
UNIQUE_VIOLATION = "23505"

# SQLSTATE нарушения CHECK — второй рубеж баланса (П3 плана 07, риск 8):
# первый рубеж — условный UPDATE в record()/purchase(), это защита на
# случай, если его обойти (риск 2 этапа 06 — правка кода без правки
# условия).
CHECK_VIOLATION = "23514"

# SQLSTATE гонок за блокировки (решение владельца от 2026-09-14): не
# повреждение данных, а проигрыш параллельной транзакции — операцию
# можно просто повторить.
DEADLOCK_DETECTED = "40P01"
SERIALIZATION_FAILURE = "40001"
CONCURRENT_UPDATE_SQLSTATES = frozenset({DEADLOCK_DETECTED, SERIALIZATION_FAILURE})


def _sqlstate(error: DBAPIError) -> str | None:
    """SQLSTATE ошибки драйвера — ищем и в ``orig``, и в ``orig.__cause__``.

    ``error.orig`` — обёртка SQLAlchemy над драйвером; но диагностика от
    asyncpg (``sqlstate``) иногда лежит на исходном исключении в
    ``__cause__`` (тот же приём, что у ``_violated_constraint_name``).
    """
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate is not None:
        return sqlstate
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "sqlstate", None)


def concurrent_update_sqlstate(error: BaseException) -> str | None:
    """SQLSTATE дедлока/serialization failure, если это одна из этих ошибок.

    Может прийти на любом операторе транзакции и на ``commit`` — единая
    точка перехвата в ``SqlAlchemyUnitOfWork.__aexit__`` покрывает оба
    случая, не требуя правки каждого метода репозитория.
    """
    if not isinstance(error, DBAPIError):
        return None
    sqlstate = _sqlstate(error)
    return sqlstate if sqlstate in CONCURRENT_UPDATE_SQLSTATES else None


def _is_unique_violation(error: IntegrityError) -> bool:
    """Отличить нарушение уникальности от прочих нарушений целостности."""
    return getattr(error.orig, "sqlstate", None) == UNIQUE_VIOLATION


def _is_check_violation(error: IntegrityError) -> bool:
    """Отличить нарушение CHECK от прочих нарушений целостности."""
    return getattr(error.orig, "sqlstate", None) == CHECK_VIOLATION


def _violated_constraint_name(error: IntegrityError) -> str | None:
    """Имя нарушенного ограничения, если драйвер его сообщает.

    ``error.orig`` — обёртка SQLAlchemy над драйвером
    (``AsyncAdapt_asyncpg_dbapi.IntegrityError``), у неё самой атрибута
    ``constraint_name`` нет; диагностика лежит на исходном исключении
    asyncpg в ``__cause__`` (найдено при отладке гонки двух сторно).
    """
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(
        error.orig, "constraint_name", None
    )


@asynccontextmanager
async def _unique_violation_as(
    session: AsyncSession, domain_error: type[DomainError]
) -> AsyncIterator[None]:
    """Выполнить запись в SAVEPOINT, переведя конфликт в доменную ошибку.

    Откат всей транзакции пометил бы просроченными все объекты сессии,
    а не только тот, что не записался — сессия одна на транзакцию UoW.
    """
    try:
        async with session.begin_nested():
            yield
    except IntegrityError as error:
        if _is_unique_violation(error):
            raise domain_error from error
        raise


def _institution_to_domain(row: InstitutionModel) -> Institution:
    return Institution(
        id=row.id,
        name=row.name,
        kind=row.kind,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _membership_to_domain(row: MembershipModel) -> Membership:
    return Membership(
        id=row.id,
        user_id=row.user_id,
        institution_id=row.institution_id,
        role=row.role,
        status=row.status,
        created_at=row.created_at,
        invitation_id=row.invitation_id,
        display_name=row.display_name,
    )


def _invitation_to_domain(row: InvitationModel) -> Invitation:
    return Invitation(
        id=row.id,
        institution_id=row.institution_id,
        token=row.token,
        role=row.role,
        max_uses=row.max_uses,
        uses_count=row.uses_count,
        created_by=row.created_by,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


class SqlAlchemyInstitutionRepository:
    """Адаптер учреждений поверх PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, institution: Institution) -> None:
        self._session.add(
            InstitutionModel(
                id=institution.id,
                name=institution.name,
                kind=institution.kind,
                created_by=institution.created_by,
                created_at=institution.created_at,
            )
        )
        await self._session.flush()

    async def get(self, institution_id: uuid.UUID) -> Institution | None:
        row = await self._session.get(InstitutionModel, institution_id)
        return _institution_to_domain(row) if row is not None else None

    async def update(self, institution: Institution) -> None:
        row = await self._session.get(InstitutionModel, institution.id)
        if row is None:
            return
        row.name = institution.name
        await self._session.flush()


class SqlAlchemyInstitutionMemberships:
    """Членства одного учреждения — привязка задаётся при сборке (H1)."""

    def __init__(self, session: AsyncSession, institution_id: uuid.UUID) -> None:
        self._session = session
        self._institution_id = institution_id

    async def add(self, membership: Membership) -> None:
        """:raises MembershipAlreadyExistsError: пара уже занята."""
        model = MembershipModel(
            id=membership.id,
            user_id=membership.user_id,
            institution_id=self._institution_id,
            role=membership.role,
            status=membership.status,
            created_at=membership.created_at,
            invitation_id=membership.invitation_id,
            display_name=membership.display_name,
        )
        async with _unique_violation_as(self._session, MembershipAlreadyExistsError):
            self._session.add(model)
            await self._session.flush()

    async def get_for_user(self, user_id: uuid.UUID) -> Membership | None:
        statement = select(MembershipModel).where(
            MembershipModel.institution_id == self._institution_id,
            MembershipModel.user_id == user_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _membership_to_domain(row) if row is not None else None

    async def get_by_id(self, membership_id: uuid.UUID) -> Membership | None:
        statement = select(MembershipModel).where(
            MembershipModel.id == membership_id,
            MembershipModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _membership_to_domain(row) if row is not None else None

    async def list_by_role(self, role: UserRole) -> list[Membership]:
        statement = select(MembershipModel).where(
            MembershipModel.institution_id == self._institution_id,
            MembershipModel.role == role,
        )
        result = await self._session.execute(statement)
        return [_membership_to_domain(row) for row in result.scalars().all()]

    async def update(self, membership: Membership) -> None:
        statement = select(MembershipModel).where(
            MembershipModel.id == membership.id,
            MembershipModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return
        row.display_name = membership.display_name
        row.status = membership.status
        await self._session.flush()


class SqlAlchemyUserMemberships:
    """Межарендная операция: собственные членства пользователя (H1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        """:see: ``app.business.ports.UserMemberships.list_for_user`` (В1/X1).

        Межарендная политика ``memberships`` (миграция ``0004``) сверх
        текущего ``app.institution_id`` пускает и собственные членства
        пользователя — по ``app.user_id``, выставленному здесь же
        параметром, а не форматированием строки.
        """
        await self._session.execute(
            text("SELECT set_config('app.user_id', :value, true)"),
            {"value": str(user_id)},
        )
        statement = select(MembershipModel).where(MembershipModel.user_id == user_id)
        result = await self._session.execute(statement)
        return [_membership_to_domain(row) for row in result.scalars().all()]


class SqlAlchemyInstitutionInvitations:
    """Приглашения одного учреждения — привязка задаётся при сборке (H1)."""

    def __init__(self, session: AsyncSession, institution_id: uuid.UUID) -> None:
        self._session = session
        self._institution_id = institution_id

    async def add(self, invitation: Invitation) -> None:
        model = InvitationModel(
            id=invitation.id,
            institution_id=self._institution_id,
            token=invitation.token,
            role=invitation.role,
            max_uses=invitation.max_uses,
            uses_count=invitation.uses_count,
            created_by=invitation.created_by,
            created_at=invitation.created_at,
            revoked_at=invitation.revoked_at,
        )
        self._session.add(model)
        await self._session.flush()

    async def get(self, invitation_id: uuid.UUID) -> Invitation | None:
        statement = select(InvitationModel).where(
            InvitationModel.id == invitation_id,
            InvitationModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _invitation_to_domain(row) if row is not None else None

    async def list_all(self) -> list[Invitation]:
        statement = select(InvitationModel).where(
            InvitationModel.institution_id == self._institution_id
        )
        result = await self._session.execute(statement)
        return [_invitation_to_domain(row) for row in result.scalars().all()]

    async def revoke(self, invitation_id: uuid.UUID) -> None:
        """:see: ``app.business.ports.InvitationRepository.revoke`` — идемпотентно."""
        statement = select(InvitationModel).where(
            InvitationModel.id == invitation_id,
            InvitationModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await self._session.flush()


class SqlAlchemyInvitationLookup:
    """Межарендная операция: поиск приглашения по токену при принятии (H1)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_accept(self, token: str) -> Invitation | None:
        """:see: ``app.business.ports.InvitationLookup.get_for_accept`` (В1/X1).

        Межарендная политика ``invitations`` (миграция ``0004``) сверх
        текущего ``app.institution_id`` пускает приглашение по
        предъявленному токену — выставленному здесь параметром
        (``hide_parameters=True`` у движка, F5: токен не должен попасть в
        текст ошибки форматированием строки).
        """
        await self._session.execute(
            text("SELECT set_config('app.invitation_token', :value, true)"),
            {"value": token},
        )
        statement = (
            select(InvitationModel)
            .where(InvitationModel.token == token)
            .with_for_update()
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _invitation_to_domain(row) if row is not None else None

    async def increment_uses(self, invitation_id: uuid.UUID) -> None:
        row = await self._session.get(InvitationModel, invitation_id)
        if row is not None:
            row.uses_count += 1
            await self._session.flush()


def _group_to_domain(row: GroupModel) -> Group:
    return Group(
        id=row.id,
        institution_id=row.institution_id,
        name=row.name,
        created_at=row.created_at,
    )


class SqlAlchemyGroupRepository:
    """Группы одного учреждения — привязка задаётся при сборке (H1).

    Уникальность имени без учёта регистра держит функциональный индекс
    БД (``uq_groups_institution_id_lower_name``), а не предварительный
    ``SELECT`` — тот не защищает от гонки (тот же принцип, что и у
    ``SqlAlchemyInstitutionMemberships.add``).
    """

    def __init__(self, session: AsyncSession, institution_id: uuid.UUID) -> None:
        self._session = session
        self._institution_id = institution_id

    async def add(self, group: Group) -> None:
        model = GroupModel(
            id=group.id,
            institution_id=self._institution_id,
            name=group.name,
            created_at=group.created_at,
        )
        async with _unique_violation_as(self._session, GroupNameTakenError):
            self._session.add(model)
            await self._session.flush()

    async def get(self, group_id: uuid.UUID) -> Group | None:
        statement = select(GroupModel).where(
            GroupModel.id == group_id,
            GroupModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _group_to_domain(row) if row is not None else None

    async def list_all(self) -> list[Group]:
        statement = select(GroupModel).where(
            GroupModel.institution_id == self._institution_id
        )
        result = await self._session.execute(statement)
        return [_group_to_domain(row) for row in result.scalars().all()]

    async def rename(self, group_id: uuid.UUID, name: str) -> Group | None:
        statement = select(GroupModel).where(
            GroupModel.id == group_id,
            GroupModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        async with _unique_violation_as(self._session, GroupNameTakenError):
            row.name = name
            await self._session.flush()
        return _group_to_domain(row)

    async def delete(self, group_id: uuid.UUID) -> bool:
        statement = select(GroupModel).where(
            GroupModel.id == group_id,
            GroupModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    def _eligible_pair(self, *, group_id: uuid.UUID, membership_id: uuid.UUID):
        """Пара (group_id, membership_id), только если обе принадлежат
        этому учреждению (H1) — источник для ``INSERT ... SELECT``.

        Строится как две независимые проверки ``EXISTS``, а не через join
        двух несвязанных таблиц: последний дал бы декартово произведение
        (SAWarning), хотя обе стороны и так однозначно определены id.
        """
        group_in_scope = (
            select(GroupModel.id)
            .where(
                GroupModel.id == group_id,
                GroupModel.institution_id == self._institution_id,
            )
            .exists()
        )
        membership_in_scope = (
            select(MembershipModel.id)
            .where(
                MembershipModel.id == membership_id,
                MembershipModel.institution_id == self._institution_id,
            )
            .exists()
        )
        return select(
            literal(group_id).label("group_id"),
            literal(membership_id).label("membership_id"),
        ).where(group_in_scope, membership_in_scope)

    async def add_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        statement = (
            postgresql.insert(GroupTeacherModel)
            .from_select(
                ["group_id", "membership_id"],
                self._eligible_pair(group_id=group_id, membership_id=membership_id),
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def remove_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        statement = delete(GroupTeacherModel).where(
            GroupTeacherModel.group_id == group_id,
            GroupTeacherModel.membership_id == membership_id,
            GroupTeacherModel.group_id.in_(
                select(GroupModel.id).where(
                    GroupModel.institution_id == self._institution_id
                )
            ),
            GroupTeacherModel.membership_id.in_(
                select(MembershipModel.id).where(
                    MembershipModel.institution_id == self._institution_id
                )
            ),
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def add_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        statement = (
            postgresql.insert(GroupStudentModel)
            .from_select(
                ["group_id", "membership_id"],
                self._eligible_pair(group_id=group_id, membership_id=membership_id),
            )
            .on_conflict_do_nothing()
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def remove_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        statement = delete(GroupStudentModel).where(
            GroupStudentModel.group_id == group_id,
            GroupStudentModel.membership_id == membership_id,
            GroupStudentModel.group_id.in_(
                select(GroupModel.id).where(
                    GroupModel.institution_id == self._institution_id
                )
            ),
            GroupStudentModel.membership_id.in_(
                select(MembershipModel.id).where(
                    MembershipModel.institution_id == self._institution_id
                )
            ),
        )
        await self._session.execute(statement)
        await self._session.flush()

    async def list_teacher_user_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        statement = (
            select(MembershipModel.user_id)
            .join(
                GroupTeacherModel,
                GroupTeacherModel.membership_id == MembershipModel.id,
            )
            .join(GroupModel, GroupModel.id == GroupTeacherModel.group_id)
            .where(
                GroupTeacherModel.group_id == group_id,
                GroupModel.institution_id == self._institution_id,
                MembershipModel.institution_id == self._institution_id,
            )
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def count_students(self, group_id: uuid.UUID) -> int:
        statement = (
            select(func.count())
            .select_from(GroupStudentModel)
            .join(GroupModel, GroupModel.id == GroupStudentModel.group_id)
            .where(
                GroupStudentModel.group_id == group_id,
                GroupModel.institution_id == self._institution_id,
            )
        )
        result = await self._session.execute(statement)
        return int(result.scalar_one())

    async def list_group_ids_for_teacher(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        statement = (
            select(GroupTeacherModel.group_id)
            .join(GroupModel, GroupModel.id == GroupTeacherModel.group_id)
            .join(
                MembershipModel,
                MembershipModel.id == GroupTeacherModel.membership_id,
            )
            .where(
                GroupTeacherModel.membership_id == membership_id,
                GroupModel.institution_id == self._institution_id,
                MembershipModel.institution_id == self._institution_id,
            )
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def list_group_ids_for_student(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        statement = (
            select(GroupStudentModel.group_id)
            .join(GroupModel, GroupModel.id == GroupStudentModel.group_id)
            .join(
                MembershipModel,
                MembershipModel.id == GroupStudentModel.membership_id,
            )
            .where(
                GroupStudentModel.membership_id == membership_id,
                GroupModel.institution_id == self._institution_id,
                MembershipModel.institution_id == self._institution_id,
            )
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())


def _currency_transaction_to_domain(
    row: CurrencyTransactionModel,
) -> CurrencyTransaction:
    return CurrencyTransaction(
        id=row.id,
        institution_id=row.institution_id,
        membership_id=row.membership_id,
        kind=TransactionKind(row.kind),
        amount=row.amount,
        comment=row.comment,
        created_by_membership_id=row.created_by_membership_id,
        operation_id=row.operation_id,
        reverses_id=row.reverses_id,
        created_at=row.created_at,
    )


@asynccontextmanager
async def _currency_unique_violation_translated(
    session: AsyncSession,
) -> AsyncIterator[None]:
    """Как ``_unique_violation_as``, но различает два ограничения (риск 1).

    ``UNIQUE(institution_id, operation_id)`` — ``operation_id`` занят
    другой операцией (``OperationIdConflictError``); ``UNIQUE(reverses_id)``
    — эту запись уже сторнировали (``TransactionAlreadyReversedError``,
    гонка двух параллельных сторно, план 06 раздел «Уточнения»);
    ``CHECK (balance >= 0)`` — второй рубеж баланса (план 07, П3/RV1,
    риск 8) поверх условного ``UPDATE`` в ``record()``/``purchase()``.
    """
    try:
        async with session.begin_nested():
            yield
    except IntegrityError as error:
        if _is_check_violation(error):
            raise InsufficientBalanceError from error
        if not _is_unique_violation(error):
            raise
        constraint = _violated_constraint_name(error)
        if constraint == CURRENCY_REVERSES_ID_UNIQUE_CONSTRAINT:
            raise TransactionAlreadyReversedError from error
        raise OperationIdConflictError from error


class SqlAlchemyCurrencyRepository:
    """Валюта одного учреждения — привязка задаётся при сборке (H1).

    Методов изменения и удаления нет (У4): порт их не объявляет, а
    таблица защищена триггером БД (миграция ``0003``).
    """

    def __init__(self, session: AsyncSession, institution_id: uuid.UUID) -> None:
        self._session = session
        self._institution_id = institution_id

    async def record(self, transaction: CurrencyTransaction) -> None:
        """Записать операцию и обновить баланс — атомарно и в границах
        учреждения (H1).

        ``membership_id``, ``created_by_membership_id`` и (для сторно)
        ``reverses_id`` приходят из сущности и не проверены вызывающим
        кодом сами по себе — принадлежность цели, автора и сторнируемой
        записи ``self._institution_id`` держит ``INSERT … SELECT … WHERE
        EXISTS``, тот же приём, что и
        ``SqlAlchemyGroupRepository._eligible_pair``, а не предварительный
        ``SELECT`` — тот не защищает от гонки. Упсерт баланса огорожен тем
        же условием через ``where=`` у ``ON CONFLICT``.

        Отрицательная сумма (сторно, план 07 В4/RV1) идёт отдельным
        условным ``UPDATE … WHERE balance + amount >= 0`` (а не через
        ``ON CONFLICT … WHERE``, см. комментарий ниже) — первый рубеж П3;
        если условие не проходит, строка не находится, и по нулевому
        ``rowcount`` бросается ``InsufficientBalanceError``. ``CHECK
        (balance >= 0)`` — второй рубеж на случай начальной вставки строки
        баланса с отрицательным значением (риск 8 плана 07), переводится в
        ``_currency_unique_violation_translated``.
        """
        eligibility = [
            select(MembershipModel.id)
            .where(
                MembershipModel.id == transaction.membership_id,
                MembershipModel.institution_id == self._institution_id,
            )
            .exists(),
            select(MembershipModel.id)
            .where(
                MembershipModel.id == transaction.created_by_membership_id,
                MembershipModel.institution_id == self._institution_id,
            )
            .exists(),
        ]
        if transaction.reverses_id is not None:
            eligibility.append(
                select(CurrencyTransactionModel.id)
                .where(
                    CurrencyTransactionModel.id == transaction.reverses_id,
                    CurrencyTransactionModel.institution_id == self._institution_id,
                )
                .exists()
            )

        eligible_row = select(
            literal(transaction.id).label("id"),
            literal(self._institution_id).label("institution_id"),
            literal(transaction.membership_id).label("membership_id"),
            literal(str(transaction.kind)).label("kind"),
            literal(transaction.amount).label("amount"),
            literal(
                transaction.comment, type_=CurrencyTransactionModel.comment.type
            ).label("comment"),
            literal(transaction.created_by_membership_id).label(
                "created_by_membership_id"
            ),
            literal(transaction.operation_id).label("operation_id"),
            literal(
                transaction.reverses_id,
                type_=CurrencyTransactionModel.reverses_id.type,
            ).label("reverses_id"),
            literal(transaction.created_at).label("created_at"),
        ).where(*eligibility)

        insert_transaction = postgresql.insert(CurrencyTransactionModel).from_select(
            [
                "id",
                "institution_id",
                "membership_id",
                "kind",
                "amount",
                "comment",
                "created_by_membership_id",
                "operation_id",
                "reverses_id",
                "created_at",
            ],
            eligible_row,
        )
        # Упсерт баланса (У2) в той же (вложенной) транзакции, что и
        # вставка истории — будущему атомарному списанию нужна отдельная
        # таблица баланса, а не ``SUM`` по истории на лету. ``where=``
        # исключает апдейт чужого баланса, если строка на него уже как-то
        # завелась (H1).
        #
        # Отрицательная сумма (сторно, план 07 В4/RV1) идёт **не** через
        # ``INSERT … ON CONFLICT DO UPDATE``, а через отдельный условный
        # ``UPDATE``: PostgreSQL проверяет CHECK на самой строке-кандидате
        # ``INSERT``, даже если конфликт в итоге уводит выполнение в ветку
        # ``DO UPDATE`` — упсерт со значением ``balance=amount`` (отрицательным)
        # падал бы на CHECK ещё до попытки обновить существующую строку
        # (найдено на прогоне db-тестов, риск 8 плана). Отсутствие строки
        # при отрицательной сумме равносильно балансу 0 — ``UPDATE`` не
        # находит её и тоже даёт ``rowcount == 0``.
        if transaction.amount < 0:
            balance_statement = (
                update(CurrencyBalanceModel)
                .where(
                    CurrencyBalanceModel.membership_id == transaction.membership_id,
                    CurrencyBalanceModel.institution_id == self._institution_id,
                    CurrencyBalanceModel.balance + transaction.amount >= 0,
                )
                .values(
                    balance=CurrencyBalanceModel.balance + transaction.amount,
                    updated_at=func.now(),
                )
            )
        else:
            balance_statement = (
                postgresql.insert(CurrencyBalanceModel)
                .values(
                    membership_id=transaction.membership_id,
                    institution_id=self._institution_id,
                    balance=transaction.amount,
                )
                .on_conflict_do_update(
                    index_elements=[CurrencyBalanceModel.membership_id],
                    set_={
                        "balance": CurrencyBalanceModel.balance + transaction.amount,
                        "updated_at": func.now(),
                    },
                    where=CurrencyBalanceModel.institution_id == self._institution_id,
                )
            )
        async with _currency_unique_violation_translated(self._session):
            result = await self._session.execute(insert_transaction)
            if result.rowcount == 0:
                # Гонка/чужое учреждение (H1) — какое условие не прошло,
                # определяем только для выбора ошибки, не для самой
                # защиты: та уже сработала в атомарном INSERT выше.
                if transaction.reverses_id is not None:
                    original_in_scope = await self._session.scalar(
                        select(CurrencyTransactionModel.id).where(
                            CurrencyTransactionModel.id == transaction.reverses_id,
                            CurrencyTransactionModel.institution_id
                            == self._institution_id,
                        )
                    )
                    if original_in_scope is None:
                        raise TransactionNotFoundError
                raise MemberNotFoundError
            balance_result = await self._session.execute(balance_statement)
            if transaction.amount < 0 and balance_result.rowcount == 0:
                raise InsufficientBalanceError

    async def get(self, transaction_id: uuid.UUID) -> CurrencyTransaction | None:
        statement = select(CurrencyTransactionModel).where(
            CurrencyTransactionModel.id == transaction_id,
            CurrencyTransactionModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _currency_transaction_to_domain(row) if row is not None else None

    async def get_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> CurrencyTransaction | None:
        statement = select(CurrencyTransactionModel).where(
            CurrencyTransactionModel.institution_id == self._institution_id,
            CurrencyTransactionModel.operation_id == operation_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _currency_transaction_to_domain(row) if row is not None else None

    async def get_balance(self, membership_id: uuid.UUID) -> int:
        statement = select(CurrencyBalanceModel.balance).where(
            CurrencyBalanceModel.institution_id == self._institution_id,
            CurrencyBalanceModel.membership_id == membership_id,
        )
        result = await self._session.execute(statement)
        balance = result.scalar_one_or_none()
        return int(balance) if balance is not None else 0

    async def list_balances(
        self, membership_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        if not membership_ids:
            return {}
        statement = select(
            CurrencyBalanceModel.membership_id, CurrencyBalanceModel.balance
        ).where(
            CurrencyBalanceModel.institution_id == self._institution_id,
            CurrencyBalanceModel.membership_id.in_(membership_ids),
        )
        result = await self._session.execute(statement)
        balances = {row.membership_id: int(row.balance) for row in result}
        # Нет строки — баланс 0 (У2); заполняется на все запрошенные id,
        # а не только на найденные, чтобы оба адаптера вели себя одинаково.
        return {
            membership_id: balances.get(membership_id, 0)
            for membership_id in membership_ids
        }

    async def list_transactions(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[CurrencyTransaction]:
        statement = (
            select(CurrencyTransactionModel)
            .where(
                CurrencyTransactionModel.institution_id == self._institution_id,
                CurrencyTransactionModel.membership_id == membership_id,
            )
            .order_by(
                CurrencyTransactionModel.created_at.desc(),
                CurrencyTransactionModel.id.desc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_currency_transaction_to_domain(row) for row in result.scalars().all()]


def _privilege_to_domain(row: PrivilegeModel) -> Privilege:
    return Privilege(
        id=row.id,
        institution_id=row.institution_id,
        title=row.title,
        description=row.description,
        price=row.price,
        stock=row.stock,
        is_active=row.is_active,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _purchase_to_domain(row: PurchaseModel) -> Purchase:
    return Purchase(
        id=row.id,
        institution_id=row.institution_id,
        membership_id=row.membership_id,
        privilege_id=row.privilege_id,
        title=row.title,
        price=row.price,
        status=PurchaseStatus(row.status),
        operation_id=row.operation_id,
        debit_transaction_id=row.debit_transaction_id,
        refund_transaction_id=row.refund_transaction_id,
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolved_by_membership_id=row.resolved_by_membership_id,
    )


class SqlAlchemyMarketRepository:
    """Маркет одного учреждения — привязка задаётся при сборке (H1).

    Каталогом управляет только admin (П2) — эта проверка в use case, а
    не здесь. Покупка, отказ и списание валюты используют тот же приём
    условного ``UPDATE``, что ``SqlAlchemyCurrencyRepository.record``
    (первый рубеж П3), и тот же перевод SQLSTATE через
    ``_currency_unique_violation_translated`` (второй рубеж, риск 8
    плана 07).
    """

    def __init__(self, session: AsyncSession, institution_id: uuid.UUID) -> None:
        self._session = session
        self._institution_id = institution_id

    async def add_privilege(self, privilege: Privilege) -> None:
        self._session.add(
            PrivilegeModel(
                id=privilege.id,
                institution_id=self._institution_id,
                title=privilege.title,
                description=privilege.description,
                price=privilege.price,
                stock=privilege.stock,
                is_active=privilege.is_active,
                created_at=privilege.created_at,
                updated_at=privilege.updated_at,
            )
        )
        await self._session.flush()

    async def get_privilege(self, privilege_id: uuid.UUID) -> Privilege | None:
        statement = select(PrivilegeModel).where(
            PrivilegeModel.id == privilege_id,
            PrivilegeModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _privilege_to_domain(row) if row is not None else None

    async def list_privileges(self, *, active_only: bool) -> list[Privilege]:
        statement = select(PrivilegeModel).where(
            PrivilegeModel.institution_id == self._institution_id
        )
        if active_only:
            statement = statement.where(PrivilegeModel.is_active.is_(True))
        statement = statement.order_by(PrivilegeModel.created_at, PrivilegeModel.id)
        result = await self._session.execute(statement)
        return [_privilege_to_domain(row) for row in result.scalars().all()]

    async def update_privilege(self, privilege: Privilege) -> Privilege | None:
        statement = select(PrivilegeModel).where(
            PrivilegeModel.id == privilege.id,
            PrivilegeModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.title = privilege.title
        row.description = privilege.description
        row.price = privilege.price
        row.stock = privilege.stock
        row.is_active = privilege.is_active
        row.updated_at = privilege.updated_at
        await self._session.flush()
        return _privilege_to_domain(row)

    async def purchase(
        self,
        *,
        membership_id: uuid.UUID,
        privilege_id: uuid.UUID,
        expected_price: int,
        operation_id: uuid.UUID,
        created_at: datetime,
    ) -> Purchase:
        """:see: ``app.business.ports.MarketRepository.purchase``.

        Порядок блокировок «позиция → баланс» (план 07, риск 1):
        сначала ``UPDATE privileges`` (остаток), затем ``UPDATE
        currency_balances`` (первый рубеж П3), затем история и сама
        покупка — один SAVEPOINT.
        """
        async with _currency_unique_violation_translated(self._session):
            stock_expr = case(
                (PrivilegeModel.stock.is_(None), None),
                else_=PrivilegeModel.stock - 1,
            )
            update_privilege = (
                update(PrivilegeModel)
                .where(
                    PrivilegeModel.id == privilege_id,
                    PrivilegeModel.institution_id == self._institution_id,
                    PrivilegeModel.is_active.is_(True),
                    or_(PrivilegeModel.stock.is_(None), PrivilegeModel.stock > 0),
                )
                .values(stock=stock_expr, updated_at=func.now())
                .returning(PrivilegeModel.price, PrivilegeModel.title)
            )
            privilege_result = await self._session.execute(update_privilege)
            privilege_row = privilege_result.first()
            if privilege_row is None:
                # Чтение — только для выбора кода: защита уже сработала в
                # самом UPDATE выше (H1, В5/L2).
                existing = await self._session.execute(
                    select(PrivilegeModel.is_active, PrivilegeModel.stock).where(
                        PrivilegeModel.id == privilege_id,
                        PrivilegeModel.institution_id == self._institution_id,
                    )
                )
                existing_row = existing.first()
                if existing_row is None or not existing_row.is_active:
                    # Скрытая позиция (is_active=False) для покупателя —
                    # то же самое, что несуществующая (У3 плана 07).
                    raise PrivilegeNotFoundError
                raise OutOfStockError

            price, title = privilege_row.price, privilege_row.title
            if price != expected_price:
                raise PriceChangedError

            update_balance = (
                update(CurrencyBalanceModel)
                .where(
                    CurrencyBalanceModel.membership_id == membership_id,
                    CurrencyBalanceModel.institution_id == self._institution_id,
                    CurrencyBalanceModel.balance >= expected_price,
                )
                .values(
                    balance=CurrencyBalanceModel.balance - expected_price,
                    updated_at=func.now(),
                )
            )
            balance_result = await self._session.execute(update_balance)
            if balance_result.rowcount == 0:
                raise InsufficientBalanceError

            debit_id = uuid.uuid4()
            await self._session.execute(
                postgresql.insert(CurrencyTransactionModel).values(
                    id=debit_id,
                    institution_id=self._institution_id,
                    membership_id=membership_id,
                    kind=str(TransactionKind.PURCHASE),
                    amount=-expected_price,
                    comment=None,
                    created_by_membership_id=membership_id,
                    operation_id=operation_id,
                    reverses_id=None,
                    created_at=created_at,
                )
            )
            purchase_id = uuid.uuid4()
            await self._session.execute(
                postgresql.insert(PurchaseModel).values(
                    id=purchase_id,
                    institution_id=self._institution_id,
                    membership_id=membership_id,
                    privilege_id=privilege_id,
                    title=title,
                    price=expected_price,
                    status=str(PurchaseStatus.PENDING),
                    operation_id=operation_id,
                    debit_transaction_id=debit_id,
                    refund_transaction_id=None,
                    created_at=created_at,
                    resolved_at=None,
                    resolved_by_membership_id=None,
                )
            )
        return Purchase(
            id=purchase_id,
            institution_id=self._institution_id,
            membership_id=membership_id,
            privilege_id=privilege_id,
            title=title,
            price=expected_price,
            status=PurchaseStatus.PENDING,
            operation_id=operation_id,
            debit_transaction_id=debit_id,
            refund_transaction_id=None,
            created_at=created_at,
            resolved_at=None,
            resolved_by_membership_id=None,
        )

    async def get_purchase(self, purchase_id: uuid.UUID) -> Purchase | None:
        statement = select(PurchaseModel).where(
            PurchaseModel.id == purchase_id,
            PurchaseModel.institution_id == self._institution_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _purchase_to_domain(row) if row is not None else None

    async def get_purchase_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> Purchase | None:
        statement = select(PurchaseModel).where(
            PurchaseModel.institution_id == self._institution_id,
            PurchaseModel.operation_id == operation_id,
        )
        result = await self._session.execute(statement)
        row = result.scalar_one_or_none()
        return _purchase_to_domain(row) if row is not None else None

    async def list_my_purchases(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[Purchase]:
        statement = (
            select(PurchaseModel)
            .where(
                PurchaseModel.institution_id == self._institution_id,
                PurchaseModel.membership_id == membership_id,
            )
            .order_by(PurchaseModel.created_at.desc(), PurchaseModel.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [_purchase_to_domain(row) for row in result.scalars().all()]

    async def list_purchases(
        self,
        *,
        status: PurchaseStatus | None,
        membership_id: uuid.UUID | None,
        limit: int | None,
    ) -> list[Purchase]:
        statement = select(PurchaseModel).where(
            PurchaseModel.institution_id == self._institution_id
        )
        if status is not None:
            statement = statement.where(PurchaseModel.status == str(status))
        if membership_id is not None:
            statement = statement.where(PurchaseModel.membership_id == membership_id)
        statement = statement.order_by(
            PurchaseModel.created_at.desc(), PurchaseModel.id.desc()
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [_purchase_to_domain(row) for row in result.scalars().all()]

    async def resolve_fulfil(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
    ) -> Purchase:
        statement = (
            update(PurchaseModel)
            .where(
                PurchaseModel.id == purchase_id,
                PurchaseModel.institution_id == self._institution_id,
                PurchaseModel.status == str(PurchaseStatus.PENDING),
            )
            .values(
                status=str(PurchaseStatus.FULFILLED),
                resolved_at=now,
                resolved_by_membership_id=resolved_by_membership_id,
            )
        )
        result = await self._session.execute(statement)
        current = await self.get_purchase(purchase_id)
        if current is None:
            raise PurchaseNotFoundError
        if result.rowcount == 1:
            return current
        # Гонка «выдать против отклонить» (У9): UPDATE … WHERE
        # status='pending' решает, кто применился, проигравший перечитывает
        # итог и либо получает тот же исход (идемпотентно), либо конфликт.
        if current.status is PurchaseStatus.FULFILLED:
            return current
        raise PurchaseAlreadyResolvedError

    async def resolve_reject(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
        refund_operation_id: uuid.UUID,
    ) -> Purchase:
        async with _currency_unique_violation_translated(self._session):
            statement = (
                update(PurchaseModel)
                .where(
                    PurchaseModel.id == purchase_id,
                    PurchaseModel.institution_id == self._institution_id,
                    PurchaseModel.status == str(PurchaseStatus.PENDING),
                )
                .values(
                    status=str(PurchaseStatus.REJECTED),
                    resolved_at=now,
                    resolved_by_membership_id=resolved_by_membership_id,
                )
                .returning(
                    PurchaseModel.membership_id,
                    PurchaseModel.privilege_id,
                    PurchaseModel.price,
                )
            )
            result = await self._session.execute(statement)
            row = result.first()
            if row is None:
                current = await self.get_purchase(purchase_id)
                if current is None:
                    raise PurchaseNotFoundError
                if current.status is PurchaseStatus.REJECTED:
                    return current
                raise PurchaseAlreadyResolvedError

            membership_id, privilege_id, price = (
                row.membership_id,
                row.privilege_id,
                row.price,
            )
            # Возврат остатка позиции (В2/M2) — stock=NULL (L2) не трогаем.
            # Порядок блокировок «позиция → баланс» (план 07, риск 1) должен
            # совпадать с ``purchase()``: иначе покупка держит позицию и ждёт
            # баланс, а отказ параллельной покупки того же ученика по той же
            # позиции держит баланс и ждёт позицию — классический дедлок
            # (``40P01``). Поэтому возврат в ``privileges`` идёт раньше
            # upsert-а баланса.
            await self._session.execute(
                update(PrivilegeModel)
                .where(
                    PrivilegeModel.id == privilege_id,
                    PrivilegeModel.institution_id == self._institution_id,
                    PrivilegeModel.stock.is_not(None),
                )
                .values(stock=PrivilegeModel.stock + 1, updated_at=func.now())
            )
            refund_id = uuid.uuid4()
            await self._session.execute(
                postgresql.insert(CurrencyTransactionModel).values(
                    id=refund_id,
                    institution_id=self._institution_id,
                    membership_id=membership_id,
                    kind=str(TransactionKind.PURCHASE_REFUND),
                    amount=price,
                    comment=None,
                    created_by_membership_id=resolved_by_membership_id,
                    operation_id=refund_operation_id,
                    reverses_id=None,
                    created_at=now,
                )
            )
            await self._session.execute(
                postgresql.insert(CurrencyBalanceModel)
                .values(
                    membership_id=membership_id,
                    institution_id=self._institution_id,
                    balance=price,
                )
                .on_conflict_do_update(
                    index_elements=[CurrencyBalanceModel.membership_id],
                    set_={
                        "balance": CurrencyBalanceModel.balance + price,
                        "updated_at": func.now(),
                    },
                    where=CurrencyBalanceModel.institution_id == self._institution_id,
                )
            )
            await self._session.execute(
                update(PurchaseModel)
                .where(PurchaseModel.id == purchase_id)
                .values(refund_transaction_id=refund_id)
            )
        current = await self.get_purchase(purchase_id)
        assert current is not None
        return current
