"""Use case'ы валюты (Ч1 плана 06): баланс ученика, ручное начисление и
сторно.

Идемпотентность строится по образцу ``AcceptInvitation`` (раздел 5 того
же плана): проверка ``operation_id`` до записи закрывает
последовательный повтор, а гонка ловится уникальным ограничением БД в
SAVEPOINT и переводится репозиторием в доменную ошибку — use case
перечитывает запись и отвечает так же, как на последовательный повтор.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.business.domain.entities import CurrencyTransaction
from app.business.domain.enums import MembershipStatus, TransactionKind, UserRole
from app.business.domain.errors import (
    OperationIdConflictError,
    StudentSuspendedError,
    TransactionNotFoundError,
)
from app.business.domain.policies import check_role, require_institution_context
from app.business.ports import Clock, InstitutionScope, UnitOfWork
from app.business.use_cases.access import (
    require_institution_admin,
    require_student_access,
)

# История отдаёт последние 50 операций, новые сверху (У1).
RECENT_TRANSACTIONS_LIMIT = 50


@dataclass(frozen=True)
class CurrencyTransactionView:
    """Элемент истории — форма ``CurrencyTransactionRead`` (раздел «Контракт»).

    ``created_by_name``/``created_by_role`` берутся из членства автора на
    момент чтения (У9), а не из снимка на момент записи.
    """

    id: uuid.UUID
    kind: TransactionKind
    amount: int
    comment: str | None
    created_by_name: str | None
    created_by_role: UserRole
    created_at: datetime
    reverses_id: uuid.UUID | None


@dataclass(frozen=True)
class CurrencyAccountView:
    """Баланс и история — форма ``CurrencyAccountRead`` (У1, У2)."""

    balance: int
    transactions: list[CurrencyTransactionView]


def _matches(
    existing: CurrencyTransaction,
    *,
    kind: TransactionKind,
    membership_id: uuid.UUID,
    amount: int,
    comment: str | None,
    reverses_id: uuid.UUID | None,
) -> bool:
    """Тот же по существу запрос — идемпотентный повтор, а не конфликт."""
    return (
        existing.kind is kind
        and existing.membership_id == membership_id
        and existing.amount == amount
        and existing.comment == comment
        and existing.reverses_id == reverses_id
    )


async def _to_transaction_view(
    scope: InstitutionScope, transaction: CurrencyTransaction
) -> CurrencyTransactionView:
    author = await scope.memberships.get_by_id(transaction.created_by_membership_id)
    # FK ``created_by_membership_id`` стоит ``ON DELETE RESTRICT`` — автор
    # не может исчезнуть, пока на него ссылается операция.
    assert author is not None
    return CurrencyTransactionView(
        id=transaction.id,
        kind=transaction.kind,
        amount=transaction.amount,
        comment=transaction.comment,
        created_by_name=author.display_name,
        created_by_role=author.role,
        created_at=transaction.created_at,
        reverses_id=transaction.reverses_id,
    )


async def _account_view(
    scope: InstitutionScope, membership_id: uuid.UUID
) -> CurrencyAccountView:
    balance = await scope.currency.get_balance(membership_id)
    transactions = await scope.currency.list_transactions(
        membership_id, limit=RECENT_TRANSACTIONS_LIMIT
    )
    views = [await _to_transaction_view(scope, tx) for tx in transactions]
    return CurrencyAccountView(balance=balance, transactions=views)


class GetMyCurrency:
    """Баланс и история собственного счёта (``GET /me/currency``, только
    ``student`` — teacher/admin получают ``INSUFFICIENT_ROLE``).
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> CurrencyAccountView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            require_institution_context(
                path_institution_id=institution_id,
                token_institution_id=actor_institution_id,
            )
            membership = await scope.memberships.get_for_user(actor_user_id)
            check_role(
                active_institution_id=actor_institution_id,
                membership=membership,
                required=(UserRole.STUDENT,),
            )
            assert membership is not None  # check_role уже это гарантировал
            return await _account_view(scope, membership.id)


class GetStudentCurrency:
    """Баланс и история ученика для teacher/admin (`GET
    /students/{user_id}/currency-transactions`)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> CurrencyAccountView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            _, student = await require_student_access(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
                target_user_id=target_user_id,
            )
            return await _account_view(scope, student.id)


class CreateAccrual:
    """Ручное начисление валюты ученику (`POST
    /students/{user_id}/currency-transactions`, В2/C2, В4/I1).

    :raises MemberNotFoundError: цель не найдена, не ученик, из другого
        учреждения или (для преподавателя) вне его групп.
    :raises StudentSuspendedError: ученик приостановлен (У6).
    :raises OperationIdConflictError: тот же ``operation_id`` уже занят
        другими параметрами.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        operation_id: uuid.UUID,
        amount: int,
        comment: str | None,
    ) -> tuple[CurrencyTransactionView, bool]:
        """Вернуть (представление, создана ли запись именно сейчас).

        Второй элемент нужен обработчику HTTP, чтобы выбрать код ответа
        (201 на создание, 200 на идемпотентный повтор).
        """
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor, student = await require_student_access(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
                target_user_id=target_user_id,
            )

            # Сначала operation_id (раздел «Уточнения к семантике»
            # плана 06): последовательный повтор не должен упираться в
            # STUDENT_SUSPENDED, если исходное начисление уже прошло.
            existing = await scope.currency.get_by_operation_id(operation_id)
            if existing is not None:
                if not _matches(
                    existing,
                    kind=TransactionKind.MANUAL_ACCRUAL,
                    membership_id=student.id,
                    amount=amount,
                    comment=comment,
                    reverses_id=None,
                ):
                    raise OperationIdConflictError
                return await _to_transaction_view(scope, existing), False

            if student.status is MembershipStatus.SUSPENDED:
                raise StudentSuspendedError

            transaction = CurrencyTransaction(
                id=uuid.uuid4(),
                institution_id=institution_id,
                membership_id=student.id,
                kind=TransactionKind.MANUAL_ACCRUAL,
                amount=amount,
                comment=comment,
                created_by_membership_id=actor.id,
                operation_id=operation_id,
                reverses_id=None,
                created_at=self._clock.now(),
            )
            try:
                await scope.currency.record(transaction)
            except OperationIdConflictError:
                # Параллельный повтор — тот же исход, что при обычном
                # повторе (идемпотентность по построению, раздел 5 плана).
                existing = await scope.currency.get_by_operation_id(operation_id)
                if existing is None:
                    raise
                if not _matches(
                    existing,
                    kind=TransactionKind.MANUAL_ACCRUAL,
                    membership_id=student.id,
                    amount=amount,
                    comment=comment,
                    reverses_id=None,
                ):
                    raise OperationIdConflictError from None
                # Читаем автора существующей записи (RLS на memberships)
                # до commit — после него app.institution_id из этой
                # транзакции уже не действует (риск 2 плана 07a).
                view = await _to_transaction_view(scope, existing)
                await uow.commit()
                return view, False

            view = await _to_transaction_view(scope, transaction)
            await uow.commit()
            return view, True


class CreateReversal:
    """Сторно ручного начисления (`POST
    /currency-transactions/{tx_id}/reversal`) — только admin (В3/E2).

    :raises TransactionNotFoundError: операции нет, она из другого
        учреждения или это уже ``reversal``.
    :raises TransactionAlreadyReversedError: операция уже сторнирована
        другой записью.
    :raises OperationIdConflictError: тот же ``operation_id`` уже занят
        другими параметрами.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        transaction_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        operation_id: uuid.UUID,
    ) -> tuple[CurrencyTransactionView, bool]:
        """Вернуть (представление, создана ли запись именно сейчас)."""
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor = await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )

            original = await scope.currency.get(transaction_id)
            if original is None or original.kind is not TransactionKind.MANUAL_ACCRUAL:
                raise TransactionNotFoundError

            expected_amount = -original.amount
            existing = await scope.currency.get_by_operation_id(operation_id)
            if existing is not None:
                if not _matches(
                    existing,
                    kind=TransactionKind.REVERSAL,
                    membership_id=original.membership_id,
                    amount=expected_amount,
                    comment=original.comment,
                    reverses_id=original.id,
                ):
                    raise OperationIdConflictError
                return await _to_transaction_view(scope, existing), False

            reversal = CurrencyTransaction(
                id=uuid.uuid4(),
                institution_id=institution_id,
                membership_id=original.membership_id,
                kind=TransactionKind.REVERSAL,
                amount=expected_amount,
                comment=original.comment,
                created_by_membership_id=actor.id,
                operation_id=operation_id,
                reverses_id=original.id,
                created_at=self._clock.now(),
            )
            try:
                await scope.currency.record(reversal)
            except OperationIdConflictError:
                existing = await scope.currency.get_by_operation_id(operation_id)
                if existing is None:
                    raise
                if not _matches(
                    existing,
                    kind=TransactionKind.REVERSAL,
                    membership_id=original.membership_id,
                    amount=expected_amount,
                    comment=original.comment,
                    reverses_id=original.id,
                ):
                    raise OperationIdConflictError from None
                # До commit (риск 2 плана 07a) — см. CreateAccrual выше.
                view = await _to_transaction_view(scope, existing)
                await uow.commit()
                return view, False
            # TransactionAlreadyReversedError — гонка на UNIQUE(reverses_id)
            # или обычный повторный сторно с новым operation_id (раздел
            # «Уточнения к семантике» плана 06) — распространяется как есть.

            view = await _to_transaction_view(scope, reversal)
            await uow.commit()
            return view, True
