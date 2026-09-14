"""In-memory реализация бизнес-портов: тесты и режим ``storage_backend=memory``.

Читающие методы возвращают **копию** сущности, а не хранимый объект:
адаптер PostgreSQL отдаёт объект сессии, и опора тестов на алиасинг дала
бы расхождение поведения между реализациями.
"""

import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

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


@dataclass
class InMemoryStore:
    """Голое хранилище: словари и ничего больше.

    Состояние отделено от поведения намеренно — тот же принцип, что и в
    ``services/users/app/repositories/memory_store.py``. При переходе на
    PostgreSQL этот класс не участвует вовсе, адаптеры меняются
    независимо от него.
    """

    institutions: dict[uuid.UUID, Institution] = field(default_factory=dict)
    memberships: dict[uuid.UUID, Membership] = field(default_factory=dict)
    membership_index: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = field(
        default_factory=dict
    )
    invitations: dict[uuid.UUID, Invitation] = field(default_factory=dict)
    invitations_by_token: dict[str, uuid.UUID] = field(default_factory=dict)
    groups: dict[uuid.UUID, Group] = field(default_factory=dict)
    # (institution_id, lower(name)) -> group_id — эмулирует функциональный
    # уникальный индекс БД (раздел 7: уникальность держит хранилище).
    group_name_index: dict[tuple[uuid.UUID, str], uuid.UUID] = field(
        default_factory=dict
    )
    group_students: set[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=set)
    group_teachers: set[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=set)
    currency_transactions: dict[uuid.UUID, CurrencyTransaction] = field(
        default_factory=dict
    )
    # (institution_id, operation_id) -> transaction_id — эмулирует
    # UNIQUE(institution_id, operation_id) (В4/I1).
    currency_operations: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = field(
        default_factory=dict
    )
    # reverses_id -> transaction_id — эмулирует UNIQUE(reverses_id) (В3/E2).
    currency_reversals: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    # membership_id -> баланс — эмулирует ``currency_balances`` (У2).
    currency_balances: dict[uuid.UUID, int] = field(default_factory=dict)
    # Каталог маркета (план 07, Ч1) — эмулирует ``privileges``/``purchases``.
    privileges: dict[uuid.UUID, Privilege] = field(default_factory=dict)
    purchases: dict[uuid.UUID, Purchase] = field(default_factory=dict)
    # (institution_id, operation_id) -> purchase_id — эмулирует
    # UNIQUE(institution_id, operation_id) на purchases; пространство
    # currency_operations общее и для списания покупки (У8 плана 06).
    purchase_operations: dict[tuple[uuid.UUID, uuid.UUID], uuid.UUID] = field(
        default_factory=dict
    )


class InMemoryInstitutionRepository:
    """Адаптер учреждений поверх словарей ``InMemoryStore``."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def add(self, institution: Institution) -> None:
        self._store.institutions[institution.id] = replace(institution)

    async def get(self, institution_id: uuid.UUID) -> Institution | None:
        institution = self._store.institutions.get(institution_id)
        return replace(institution) if institution is not None else None

    async def update(self, institution: Institution) -> None:
        stored = self._store.institutions.get(institution.id)
        if stored is None:
            return
        self._store.institutions[institution.id] = replace(
            stored, name=institution.name
        )


class InMemoryInstitutionMemberships:
    """Членства одного учреждения — привязка задаётся при сборке (H1)."""

    def __init__(self, store: InMemoryStore, institution_id: uuid.UUID) -> None:
        self._store = store
        self._institution_id = institution_id

    async def add(self, membership: Membership) -> None:
        key = (membership.user_id, self._institution_id)
        if key in self._store.membership_index:
            raise MembershipAlreadyExistsError
        stored = replace(membership, institution_id=self._institution_id)
        self._store.memberships[stored.id] = stored
        self._store.membership_index[key] = stored.id

    async def get_for_user(self, user_id: uuid.UUID) -> Membership | None:
        membership_id = self._store.membership_index.get(
            (user_id, self._institution_id)
        )
        if membership_id is None:
            return None
        membership = self._store.memberships.get(membership_id)
        return replace(membership) if membership is not None else None

    async def get_by_id(self, membership_id: uuid.UUID) -> Membership | None:
        membership = self._store.memberships.get(membership_id)
        if membership is None or membership.institution_id != self._institution_id:
            return None
        return replace(membership)

    async def list_by_role(self, role: UserRole) -> list[Membership]:
        return [
            replace(membership)
            for membership in self._store.memberships.values()
            if membership.institution_id == self._institution_id
            and membership.role is role
        ]

    async def update(self, membership: Membership) -> None:
        stored = self._store.memberships.get(membership.id)
        if stored is None or stored.institution_id != self._institution_id:
            return
        self._store.memberships[membership.id] = replace(
            stored,
            display_name=membership.display_name,
            status=membership.status,
        )


class InMemoryUserMemberships:
    """Межарендная операция: собственные членства пользователя (H1)."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def list_for_user(self, user_id: uuid.UUID) -> list[Membership]:
        return [
            replace(membership)
            for membership in self._store.memberships.values()
            if membership.user_id == user_id
        ]


class InMemoryInstitutionInvitations:
    """Приглашения одного учреждения — привязка задаётся при сборке (H1)."""

    def __init__(self, store: InMemoryStore, institution_id: uuid.UUID) -> None:
        self._store = store
        self._institution_id = institution_id

    async def add(self, invitation: Invitation) -> None:
        stored = replace(invitation, institution_id=self._institution_id)
        self._store.invitations[stored.id] = stored
        self._store.invitations_by_token[stored.token] = stored.id

    async def get(self, invitation_id: uuid.UUID) -> Invitation | None:
        invitation = self._store.invitations.get(invitation_id)
        if invitation is None or invitation.institution_id != self._institution_id:
            return None
        return replace(invitation)

    async def list_all(self) -> list[Invitation]:
        return [
            replace(invitation)
            for invitation in self._store.invitations.values()
            if invitation.institution_id == self._institution_id
        ]

    async def revoke(self, invitation_id: uuid.UUID) -> None:
        """:see: ``app.business.ports.InvitationRepository.revoke`` — идемпотентно.

        Записывает новый объект вместо мутации хранимого — снимок
        отката (``InMemoryUnitOfWork``) копирует только сам словарь, не
        значения, и мутация на месте испортила бы откат незакоммиченной
        транзакции.
        """
        invitation = self._store.invitations.get(invitation_id)
        if invitation is None or invitation.institution_id != self._institution_id:
            return
        if invitation.revoked_at is None:
            self._store.invitations[invitation_id] = replace(
                invitation, revoked_at=datetime.now(UTC)
            )


class InMemoryInvitationLookup:
    """Межарендная операция: поиск приглашения по токену при принятии (H1)."""

    def __init__(self, store: InMemoryStore) -> None:
        self._store = store

    async def get_for_accept(self, token: str) -> Invitation | None:
        invitation_id = self._store.invitations_by_token.get(token)
        if invitation_id is None:
            return None
        invitation = self._store.invitations.get(invitation_id)
        return replace(invitation) if invitation is not None else None

    async def increment_uses(self, invitation_id: uuid.UUID) -> None:
        """См. примечание в ``InMemoryInstitutionInvitations.revoke`` про откат."""
        invitation = self._store.invitations.get(invitation_id)
        if invitation is not None:
            self._store.invitations[invitation_id] = replace(
                invitation, uses_count=invitation.uses_count + 1
            )


class InMemoryGroupRepository:
    """Группы одного учреждения — привязка задаётся при сборке (H1).

    Уникальность имени без учёта регистра эмулируется индексом
    ``group_name_index``: та же роль, что у функционального индекса БД
    в ``SqlAlchemyGroupRepository`` (раздел 7 — обе реализации дают
    одинаковый наблюдаемый эффект).
    """

    def __init__(self, store: InMemoryStore, institution_id: uuid.UUID) -> None:
        self._store = store
        self._institution_id = institution_id

    def _name_key(self, name: str) -> tuple[uuid.UUID, str]:
        return (self._institution_id, name.lower())

    async def add(self, group: Group) -> None:
        key = self._name_key(group.name)
        if key in self._store.group_name_index:
            raise GroupNameTakenError
        stored = replace(group, institution_id=self._institution_id)
        self._store.groups[stored.id] = stored
        self._store.group_name_index[key] = stored.id

    async def get(self, group_id: uuid.UUID) -> Group | None:
        group = self._store.groups.get(group_id)
        if group is None or group.institution_id != self._institution_id:
            return None
        return replace(group)

    async def list_all(self) -> list[Group]:
        return [
            replace(group)
            for group in self._store.groups.values()
            if group.institution_id == self._institution_id
        ]

    async def rename(self, group_id: uuid.UUID, name: str) -> Group | None:
        group = self._store.groups.get(group_id)
        if group is None or group.institution_id != self._institution_id:
            return None
        new_key = self._name_key(name)
        old_key = self._name_key(group.name)
        if new_key != old_key and new_key in self._store.group_name_index:
            raise GroupNameTakenError
        updated = replace(group, name=name)
        self._store.groups[group_id] = updated
        del self._store.group_name_index[old_key]
        self._store.group_name_index[new_key] = group_id
        return replace(updated)

    async def delete(self, group_id: uuid.UUID) -> bool:
        group = self._store.groups.get(group_id)
        if group is None or group.institution_id != self._institution_id:
            return False
        del self._store.groups[group_id]
        del self._store.group_name_index[self._name_key(group.name)]
        self._store.group_students = {
            pair for pair in self._store.group_students if pair[0] != group_id
        }
        self._store.group_teachers = {
            pair for pair in self._store.group_teachers if pair[0] != group_id
        }
        return True

    def _in_scope(self, *, group_id: uuid.UUID, membership_id: uuid.UUID) -> bool:
        """Пара (group_id, membership_id) принадлежит этому учреждению (H1)."""
        group = self._store.groups.get(group_id)
        membership = self._store.memberships.get(membership_id)
        return (
            group is not None
            and group.institution_id == self._institution_id
            and membership is not None
            and membership.institution_id == self._institution_id
        )

    async def add_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        if not self._in_scope(group_id=group_id, membership_id=membership_id):
            return
        self._store.group_teachers.add((group_id, membership_id))

    async def remove_teacher(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        if not self._in_scope(group_id=group_id, membership_id=membership_id):
            return
        self._store.group_teachers.discard((group_id, membership_id))

    async def add_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        if not self._in_scope(group_id=group_id, membership_id=membership_id):
            return
        self._store.group_students.add((group_id, membership_id))

    async def remove_student(
        self, *, group_id: uuid.UUID, membership_id: uuid.UUID
    ) -> None:
        if not self._in_scope(group_id=group_id, membership_id=membership_id):
            return
        self._store.group_students.discard((group_id, membership_id))

    async def list_teacher_user_ids(self, group_id: uuid.UUID) -> list[uuid.UUID]:
        group = self._store.groups.get(group_id)
        if group is None or group.institution_id != self._institution_id:
            return []
        membership_ids = {
            pair[1] for pair in self._store.group_teachers if pair[0] == group_id
        }
        return [
            membership.user_id
            for membership in self._store.memberships.values()
            if membership.id in membership_ids
            and membership.institution_id == self._institution_id
        ]

    async def count_students(self, group_id: uuid.UUID) -> int:
        group = self._store.groups.get(group_id)
        if group is None or group.institution_id != self._institution_id:
            return 0
        return sum(1 for pair in self._store.group_students if pair[0] == group_id)

    async def list_group_ids_for_teacher(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        membership = self._store.memberships.get(membership_id)
        if membership is None or membership.institution_id != self._institution_id:
            return []
        group_ids = []
        for pair in self._store.group_teachers:
            if pair[1] != membership_id:
                continue
            group = self._store.groups.get(pair[0])
            if group is not None and group.institution_id == self._institution_id:
                group_ids.append(pair[0])
        return group_ids

    async def list_group_ids_for_student(
        self, membership_id: uuid.UUID
    ) -> list[uuid.UUID]:
        membership = self._store.memberships.get(membership_id)
        if membership is None or membership.institution_id != self._institution_id:
            return []
        group_ids = []
        for pair in self._store.group_students:
            if pair[1] != membership_id:
                continue
            group = self._store.groups.get(pair[0])
            if group is not None and group.institution_id == self._institution_id:
                group_ids.append(pair[0])
        return group_ids


class InMemoryCurrencyRepository:
    """Валюта одного учреждения — привязка задаётся при сборке (H1).

    Повторяет семантику упсерта баланса и уникальностей PostgreSQL
    (риск 1 плана): фейковый прогон не должен быть зелёным на том, что
    ломается на живой базе.
    """

    def __init__(self, store: InMemoryStore, institution_id: uuid.UUID) -> None:
        self._store = store
        self._institution_id = institution_id

    def _membership_in_scope(self, membership_id: uuid.UUID) -> bool:
        membership = self._store.memberships.get(membership_id)
        return membership is not None and membership.institution_id == (
            self._institution_id
        )

    async def record(self, transaction: CurrencyTransaction) -> None:
        # Членство цели и автора должны принадлежать этому учреждению
        # (H1) — тот же порядок проверок, что у ``SqlAlchemyCurrencyRepository``.
        if not self._membership_in_scope(
            transaction.membership_id
        ) or not self._membership_in_scope(transaction.created_by_membership_id):
            raise MemberNotFoundError
        if transaction.reverses_id is not None:
            original = self._store.currency_transactions.get(transaction.reverses_id)
            if original is None or original.institution_id != self._institution_id:
                raise TransactionNotFoundError
        operation_key = (self._institution_id, transaction.operation_id)
        if operation_key in self._store.currency_operations:
            raise OperationIdConflictError
        if (
            transaction.reverses_id is not None
            and transaction.reverses_id in self._store.currency_reversals
        ):
            raise TransactionAlreadyReversedError
        current_balance = self._store.currency_balances.get(
            transaction.membership_id, 0
        )
        new_balance = current_balance + transaction.amount
        if new_balance < 0:
            # П3/В4/RV1: сторно, которое увело бы баланс в минус, не
            # применяется вовсе — та же семантика, что условный UPDATE в
            # SqlAlchemyCurrencyRepository.record (иначе фейки были бы
            # зелёными на том, что ломается на живой базе, риск 1 плана 06).
            raise InsufficientBalanceError
        stored = replace(transaction, institution_id=self._institution_id)
        self._store.currency_transactions[stored.id] = stored
        self._store.currency_operations[operation_key] = stored.id
        if stored.reverses_id is not None:
            self._store.currency_reversals[stored.reverses_id] = stored.id
        self._store.currency_balances[stored.membership_id] = new_balance

    async def get(self, transaction_id: uuid.UUID) -> CurrencyTransaction | None:
        transaction = self._store.currency_transactions.get(transaction_id)
        if transaction is None or transaction.institution_id != self._institution_id:
            return None
        return replace(transaction)

    async def get_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> CurrencyTransaction | None:
        transaction_id = self._store.currency_operations.get(
            (self._institution_id, operation_id)
        )
        if transaction_id is None:
            return None
        return replace(self._store.currency_transactions[transaction_id])

    async def get_balance(self, membership_id: uuid.UUID) -> int:
        # Баланс чужого учреждения не виден (L3) — та же граница, что у
        # ``SqlAlchemyCurrencyRepository.get_balance``.
        if not self._membership_in_scope(membership_id):
            return 0
        return self._store.currency_balances.get(membership_id, 0)

    async def list_balances(
        self, membership_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        return {
            membership_id: (
                self._store.currency_balances.get(membership_id, 0)
                if self._membership_in_scope(membership_id)
                else 0
            )
            for membership_id in membership_ids
        }

    async def list_transactions(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[CurrencyTransaction]:
        items = [
            transaction
            for transaction in self._store.currency_transactions.values()
            if transaction.institution_id == self._institution_id
            and transaction.membership_id == membership_id
        ]
        items.sort(key=lambda transaction: (transaction.created_at, transaction.id))
        items.reverse()
        return [replace(transaction) for transaction in items[:limit]]


class InMemoryMarketRepository:
    """Маркет одного учреждения — привязка задаётся при сборке (H1).

    Повторяет семантику атомарной покупки и CHECK-баланса SQL-адаптера
    (риск 4 плана 07: fake не должен быть зелёным там, где ломается
    живая база), включая порядок блокировок «позиция → баланс».
    """

    def __init__(self, store: InMemoryStore, institution_id: uuid.UUID) -> None:
        self._store = store
        self._institution_id = institution_id

    async def add_privilege(self, privilege: Privilege) -> None:
        self._store.privileges[privilege.id] = replace(
            privilege, institution_id=self._institution_id
        )

    async def get_privilege(self, privilege_id: uuid.UUID) -> Privilege | None:
        privilege = self._store.privileges.get(privilege_id)
        if privilege is None or privilege.institution_id != self._institution_id:
            return None
        return replace(privilege)

    async def list_privileges(self, *, active_only: bool) -> list[Privilege]:
        items = [
            privilege
            for privilege in self._store.privileges.values()
            if privilege.institution_id == self._institution_id
            and (not active_only or privilege.is_active)
        ]
        items.sort(key=lambda privilege: (privilege.created_at, privilege.id))
        return [replace(privilege) for privilege in items]

    async def update_privilege(self, privilege: Privilege) -> Privilege | None:
        stored = self._store.privileges.get(privilege.id)
        if stored is None or stored.institution_id != self._institution_id:
            return None
        updated = replace(privilege, institution_id=self._institution_id)
        self._store.privileges[privilege.id] = updated
        return replace(updated)

    async def purchase(
        self,
        *,
        membership_id: uuid.UUID,
        privilege_id: uuid.UUID,
        expected_price: int,
        operation_id: uuid.UUID,
        created_at: datetime,
    ) -> Purchase:
        operation_key = (self._institution_id, operation_id)
        if (
            operation_key in self._store.currency_operations
            or operation_key in self._store.purchase_operations
        ):
            raise OperationIdConflictError

        privilege = self._store.privileges.get(privilege_id)
        if (
            privilege is None
            or privilege.institution_id != self._institution_id
            or not privilege.is_active
        ):
            raise PrivilegeNotFoundError
        if privilege.stock is not None and privilege.stock <= 0:
            raise OutOfStockError
        if privilege.price != expected_price:
            raise PriceChangedError

        current_balance = self._store.currency_balances.get(membership_id, 0)
        if current_balance < expected_price:
            raise InsufficientBalanceError

        if privilege.stock is not None:
            self._store.privileges[privilege_id] = replace(
                privilege, stock=privilege.stock - 1
            )
        self._store.currency_balances[membership_id] = current_balance - expected_price

        debit_id = uuid.uuid4()
        debit = CurrencyTransaction(
            id=debit_id,
            institution_id=self._institution_id,
            membership_id=membership_id,
            kind=TransactionKind.PURCHASE,
            amount=-expected_price,
            comment=None,
            created_by_membership_id=membership_id,
            operation_id=operation_id,
            reverses_id=None,
            created_at=created_at,
        )
        self._store.currency_transactions[debit_id] = debit
        self._store.currency_operations[operation_key] = debit_id

        purchase_id = uuid.uuid4()
        purchase = Purchase(
            id=purchase_id,
            institution_id=self._institution_id,
            membership_id=membership_id,
            privilege_id=privilege_id,
            title=privilege.title,
            price=expected_price,
            status=PurchaseStatus.PENDING,
            operation_id=operation_id,
            debit_transaction_id=debit_id,
            refund_transaction_id=None,
            created_at=created_at,
            resolved_at=None,
            resolved_by_membership_id=None,
        )
        self._store.purchases[purchase_id] = purchase
        self._store.purchase_operations[operation_key] = purchase_id
        return replace(purchase)

    async def get_purchase(self, purchase_id: uuid.UUID) -> Purchase | None:
        purchase = self._store.purchases.get(purchase_id)
        if purchase is None or purchase.institution_id != self._institution_id:
            return None
        return replace(purchase)

    async def get_purchase_by_operation_id(
        self, operation_id: uuid.UUID
    ) -> Purchase | None:
        purchase_id = self._store.purchase_operations.get(
            (self._institution_id, operation_id)
        )
        if purchase_id is None:
            return None
        return replace(self._store.purchases[purchase_id])

    async def list_my_purchases(
        self, membership_id: uuid.UUID, *, limit: int
    ) -> list[Purchase]:
        items = [
            purchase
            for purchase in self._store.purchases.values()
            if purchase.institution_id == self._institution_id
            and purchase.membership_id == membership_id
        ]
        items.sort(key=lambda purchase: (purchase.created_at, purchase.id))
        items.reverse()
        return [replace(purchase) for purchase in items[:limit]]

    async def list_purchases(
        self,
        *,
        status: PurchaseStatus | None,
        membership_id: uuid.UUID | None,
        limit: int | None,
    ) -> list[Purchase]:
        items = [
            purchase
            for purchase in self._store.purchases.values()
            if purchase.institution_id == self._institution_id
            and (status is None or purchase.status is status)
            and (membership_id is None or purchase.membership_id == membership_id)
        ]
        items.sort(key=lambda purchase: (purchase.created_at, purchase.id))
        items.reverse()
        if limit is not None:
            items = items[:limit]
        return [replace(purchase) for purchase in items]

    async def resolve_fulfil(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
    ) -> Purchase:
        purchase = self._store.purchases.get(purchase_id)
        if purchase is None or purchase.institution_id != self._institution_id:
            raise PurchaseNotFoundError
        if purchase.status is PurchaseStatus.FULFILLED:
            return replace(purchase)
        if purchase.status is PurchaseStatus.REJECTED:
            raise PurchaseAlreadyResolvedError
        updated = replace(
            purchase,
            status=PurchaseStatus.FULFILLED,
            resolved_at=now,
            resolved_by_membership_id=resolved_by_membership_id,
        )
        self._store.purchases[purchase_id] = updated
        return replace(updated)

    async def resolve_reject(
        self,
        purchase_id: uuid.UUID,
        *,
        resolved_by_membership_id: uuid.UUID,
        now: datetime,
        refund_operation_id: uuid.UUID,
    ) -> Purchase:
        purchase = self._store.purchases.get(purchase_id)
        if purchase is None or purchase.institution_id != self._institution_id:
            raise PurchaseNotFoundError
        if purchase.status is PurchaseStatus.REJECTED:
            return replace(purchase)
        if purchase.status is PurchaseStatus.FULFILLED:
            raise PurchaseAlreadyResolvedError

        refund_id = uuid.uuid4()
        refund = CurrencyTransaction(
            id=refund_id,
            institution_id=self._institution_id,
            membership_id=purchase.membership_id,
            kind=TransactionKind.PURCHASE_REFUND,
            amount=purchase.price,
            comment=None,
            created_by_membership_id=resolved_by_membership_id,
            operation_id=refund_operation_id,
            reverses_id=None,
            created_at=now,
        )
        self._store.currency_transactions[refund_id] = refund
        self._store.currency_operations[(self._institution_id, refund_operation_id)] = (
            refund_id
        )
        current_balance = self._store.currency_balances.get(purchase.membership_id, 0)
        self._store.currency_balances[purchase.membership_id] = (
            current_balance + purchase.price
        )
        privilege = self._store.privileges.get(purchase.privilege_id)
        if privilege is not None and privilege.stock is not None:
            self._store.privileges[purchase.privilege_id] = replace(
                privilege, stock=privilege.stock + 1
            )

        updated = replace(
            purchase,
            status=PurchaseStatus.REJECTED,
            resolved_at=now,
            resolved_by_membership_id=resolved_by_membership_id,
            refund_transaction_id=refund_id,
        )
        self._store.purchases[purchase_id] = updated
        return replace(updated)
