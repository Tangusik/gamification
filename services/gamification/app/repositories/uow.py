"""Unit of Work: одна транзакция на use case, коммит один раз (раздел 7).

Две реализации одного порта (``app.business.ports.UnitOfWork``) — в
памяти для тестов и режима ``storage_backend=memory``, поверх
PostgreSQL для рантайма. Обе не коммитят ничего сами: без явного
``commit()`` выход из ``async with`` откатывает всё, что успело
записаться внутри блока.
"""

import logging
from types import TracebackType
from typing import Self
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.business.domain.errors import ConcurrentUpdateError
from app.repositories.in_memory import (
    InMemoryCurrencyRepository,
    InMemoryGroupRepository,
    InMemoryInstitutionInvitations,
    InMemoryInstitutionMemberships,
    InMemoryInstitutionRepository,
    InMemoryInvitationLookup,
    InMemoryMarketRepository,
    InMemoryStore,
    InMemoryUserMemberships,
)
from app.repositories.sql_alchemy import (
    SqlAlchemyCurrencyRepository,
    SqlAlchemyGroupRepository,
    SqlAlchemyInstitutionInvitations,
    SqlAlchemyInstitutionMemberships,
    SqlAlchemyInstitutionRepository,
    SqlAlchemyInvitationLookup,
    SqlAlchemyMarketRepository,
    SqlAlchemyUserMemberships,
    concurrent_update_sqlstate,
)

logger = logging.getLogger(__name__)


class _InMemoryInstitutionScope:
    def __init__(self, store: InMemoryStore, institution_id: UUID) -> None:
        self.memberships = InMemoryInstitutionMemberships(store, institution_id)
        self.invitations = InMemoryInstitutionInvitations(store, institution_id)
        self.groups = InMemoryGroupRepository(store, institution_id)
        self.currency = InMemoryCurrencyRepository(store, institution_id)
        self.market = InMemoryMarketRepository(store, institution_id)


class InMemoryUnitOfWork:
    """Единая псевдо-транзакция в памяти: снимок на входе, откат при сбое.

    ``add()`` пишет в общий ``InMemoryStore`` немедленно — иначе
    репозиториям пришлось бы городить собственный журнал изменений.
    Откат при выходе без ``commit()`` реализован снимком состояния,
    сделанным на входе в ``async with``: тот же наблюдаемый эффект, что
    и у ``session.rollback()`` в SQLAlchemy-варианте.
    """

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store
        self._committed = False
        self._snapshot: InMemoryStore | None = None
        self._institution_id: UUID | None = None
        self.institutions = InMemoryInstitutionRepository(store)
        self.user_memberships = InMemoryUserMemberships(store)
        self.invitation_lookup = InMemoryInvitationLookup(store)

    async def for_institution(self, institution_id: UUID) -> _InMemoryInstitutionScope:
        """:see: ``app.business.ports.UnitOfWork.for_institution`` (В3/A1).

        Реализация в памяти не выполняет ``set_config``, но повторяет ту
        же ошибку использования — иначе фейки были бы зелёными там, где
        реализация поверх PostgreSQL уже упала бы (риск 1 плана 07a).
        """
        if self._institution_id is not None and self._institution_id != institution_id:
            raise RuntimeError(
                "UnitOfWork уже выставил контекст для другого учреждения — "
                "один UoW обслуживает одно учреждение за транзакцию"
            )
        self._institution_id = institution_id
        return _InMemoryInstitutionScope(self._store, institution_id)

    async def commit(self) -> None:
        self._committed = True
        # Контекст учреждения привязан к транзакции (риск 2 плана 07a):
        # после коммита он должен выставляться заново, как и в
        # PostgreSQL-реализации, где ``set_config(..., true)`` истекает
        # вместе с транзакцией.
        self._institution_id = None

    async def __aenter__(self) -> Self:
        self._committed = False
        self._institution_id = None
        self._snapshot = InMemoryStore(
            institutions=dict(self._store.institutions),
            memberships=dict(self._store.memberships),
            membership_index=dict(self._store.membership_index),
            invitations=dict(self._store.invitations),
            invitations_by_token=dict(self._store.invitations_by_token),
            groups=dict(self._store.groups),
            group_name_index=dict(self._store.group_name_index),
            group_students=set(self._store.group_students),
            group_teachers=set(self._store.group_teachers),
            currency_transactions=dict(self._store.currency_transactions),
            currency_operations=dict(self._store.currency_operations),
            currency_reversals=dict(self._store.currency_reversals),
            currency_balances=dict(self._store.currency_balances),
            privileges=dict(self._store.privileges),
            purchases=dict(self._store.purchases),
            purchase_operations=dict(self._store.purchase_operations),
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if not self._committed and self._snapshot is not None:
            self._store.institutions = self._snapshot.institutions
            self._store.memberships = self._snapshot.memberships
            self._store.membership_index = self._snapshot.membership_index
            self._store.invitations = self._snapshot.invitations
            self._store.invitations_by_token = self._snapshot.invitations_by_token
            self._store.groups = self._snapshot.groups
            self._store.group_name_index = self._snapshot.group_name_index
            self._store.group_students = self._snapshot.group_students
            self._store.group_teachers = self._snapshot.group_teachers
            self._store.currency_transactions = self._snapshot.currency_transactions
            self._store.currency_operations = self._snapshot.currency_operations
            self._store.currency_reversals = self._snapshot.currency_reversals
            self._store.currency_balances = self._snapshot.currency_balances
            self._store.privileges = self._snapshot.privileges
            self._store.purchases = self._snapshot.purchases
            self._store.purchase_operations = self._snapshot.purchase_operations
        self._snapshot = None


class _SqlAlchemyInstitutionScope:
    def __init__(self, session: AsyncSession, institution_id: UUID) -> None:
        self.memberships = SqlAlchemyInstitutionMemberships(session, institution_id)
        self.invitations = SqlAlchemyInstitutionInvitations(session, institution_id)
        self.groups = SqlAlchemyGroupRepository(session, institution_id)
        self.currency = SqlAlchemyCurrencyRepository(session, institution_id)
        self.market = SqlAlchemyMarketRepository(session, institution_id)


class SqlAlchemyUnitOfWork:
    """Одна сессия — одна транзакция; коммит вызывает use case."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._committed = False
        self._institution_id: UUID | None = None

    def _session_required(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork используется вне 'async with'")
        return self._session

    async def for_institution(
        self, institution_id: UUID
    ) -> _SqlAlchemyInstitutionScope:
        """:see: ``app.business.ports.UnitOfWork.for_institution`` (В3/A1).

        Выставляет ``app.institution_id`` в текущей транзакции параметром
        (не форматированием строки) — политики RLS (миграция ``0004``)
        читают её через ``current_setting``. Кеш ``_institution_id``
        привязан к транзакции: повторный вызов с другим id — ошибка
        использования, а сброс на ``commit`` (риск 2 плана) не даёт
        следующему вызову в новой транзакции того же UoW тихо остаться
        без контекста.
        """
        session = self._session_required()
        if self._institution_id is not None and self._institution_id != institution_id:
            raise RuntimeError(
                "UnitOfWork уже выставил контекст для другого учреждения — "
                "один UoW обслуживает одно учреждение за транзакцию"
            )
        if self._institution_id != institution_id:
            await session.execute(
                text("SELECT set_config('app.institution_id', :value, true)"),
                {"value": str(institution_id)},
            )
            self._institution_id = institution_id
        return _SqlAlchemyInstitutionScope(session, institution_id)

    @property
    def institutions(self) -> SqlAlchemyInstitutionRepository:
        return SqlAlchemyInstitutionRepository(self._session_required())

    @property
    def user_memberships(self) -> SqlAlchemyUserMemberships:
        return SqlAlchemyUserMemberships(self._session_required())

    @property
    def invitation_lookup(self) -> SqlAlchemyInvitationLookup:
        return SqlAlchemyInvitationLookup(self._session_required())

    async def commit(self) -> None:
        await self._session_required().commit()
        self._committed = True
        # ``set_config(..., true)`` — ``is_local`` — истекает вместе с
        # транзакцией коммита (риск 2 плана 07a, ловушка A1): следующая
        # транзакция на этой же сессии не унаследует контекст, и без
        # сброса кеша ``for_institution`` тихо решил бы, что он уже
        # выставлен, и промолчал.
        self._institution_id = None

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self._committed = False
        self._institution_id = None
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self._session_required()
        try:
            if not self._committed:
                await session.rollback()
        finally:
            await session.close()
            self._session = None
        # Единая точка перехвата дедлока/serialization failure (решение
        # владельца от 2026-09-14): исключение могло прийти с любого
        # оператора транзакции внутри ``async with self._uow`` или с
        # явного ``commit()`` — оба случая проходят здесь, поэтому не
        # нужно править каждый метод репозитория отдельно.
        if exc is not None:
            sqlstate = concurrent_update_sqlstate(exc)
            if sqlstate is not None:
                logger.warning("Retryable database error: sqlstate=%s", sqlstate)
                raise ConcurrentUpdateError from exc
