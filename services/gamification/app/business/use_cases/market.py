"""Use case'ы маркета привилегий (план 07, Ч1): каталог, покупка, отказ.

Идемпотентность покупки строится по тому же образцу, что и
``CreateAccrual`` (``use_cases/currency.py``): проверка ``operation_id``
до записи закрывает последовательный повтор, гонка ловится в
``MarketRepository.purchase`` и переводится в ``OperationIdConflictError``
— use case перечитывает покупку и отвечает так же, как на
последовательный повтор (П4).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime

from app.business.domain.entities import Privilege, Purchase
from app.business.domain.enums import PurchaseStatus, UserRole
from app.business.domain.errors import (
    MemberNotFoundError,
    OperationIdConflictError,
    PrivilegeNotFoundError,
)
from app.business.domain.policies import check_role, require_institution_context
from app.business.ports import Clock, InstitutionScope, UnitOfWork
from app.business.use_cases.access import require_institution_admin

# История покупок отдаёт последние 50 (У8); очередь pending — без лимита.
RECENT_PURCHASES_LIMIT = 50

# Каталог: покупает только student (У1), управляет только admin (П2),
# но читает список любая активная роль учреждения.
CATALOGUE_VIEW_ROLES = (UserRole.STUDENT, UserRole.TEACHER, UserRole.INSTITUTION_ADMIN)
PURCHASE_ROLES = (UserRole.STUDENT,)


@dataclass(frozen=True)
class PrivilegeView:
    """Элемент каталога — форма ``PrivilegeRead`` (план 07, раздел «Эндпоинты»)."""

    id: uuid.UUID
    title: str
    description: str | None
    price: int
    stock: int | None
    is_active: bool


@dataclass(frozen=True)
class PurchaseView:
    """Элемент покупки — форма ``PurchaseRead`` (раздел 9 плана: контракт
    подтверждён владельцем). ``user_id``/``user_name`` заполняются только
    в админском списке и решениях админа."""

    id: uuid.UUID
    privilege_id: uuid.UUID
    title: str
    price: int
    status: PurchaseStatus
    created_at: datetime
    resolved_at: datetime | None
    user_id: uuid.UUID | None = None
    user_name: str | None = None


def _to_privilege_view(privilege: Privilege) -> PrivilegeView:
    return PrivilegeView(
        id=privilege.id,
        title=privilege.title,
        description=privilege.description,
        price=privilege.price,
        stock=privilege.stock,
        is_active=privilege.is_active,
    )


async def _to_purchase_view(
    scope: InstitutionScope, purchase: Purchase, *, with_member: bool
) -> PurchaseView:
    """Собрать представление покупки.

    ``with_member=True`` читает членство покупателя (RLS-таблица) — вызов
    обязан случиться до ``uow.commit()`` (риск 2 плана 07a: контекст
    учреждения снимается вместе с транзакцией).
    """
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    if with_member:
        member = await scope.memberships.get_by_id(purchase.membership_id)
        # FK purchases.membership_id — ON DELETE RESTRICT, членство не
        # может исчезнуть, пока на него ссылается покупка.
        assert member is not None
        user_id = member.user_id
        user_name = member.display_name
    return PurchaseView(
        id=purchase.id,
        privilege_id=purchase.privilege_id,
        title=purchase.title,
        price=purchase.price,
        status=purchase.status,
        created_at=purchase.created_at,
        resolved_at=purchase.resolved_at,
        user_id=user_id,
        user_name=user_name,
    )


def _apply_privilege_update(
    privilege: Privilege,
    *,
    fields: frozenset[str],
    title: str | None,
    description: str | None,
    price: int | None,
    stock: int | None,
    is_active: bool | None,
) -> Privilege:
    """Применить только переданные поля ``PATCH`` (У11).

    ``fields`` — набор имён полей, пришедших в теле запроса
    (``model_fields_set`` схемы); отсутствие имени в наборе значит «поле
    не передано», а не «сбросить в ``None``» — это единственный способ
    отличить непереданный ``stock``/``description`` от явного ``null``.
    """
    updated = privilege
    if "title" in fields:
        assert title is not None
        updated = replace(updated, title=title)
    if "description" in fields:
        updated = replace(updated, description=description)
    if "price" in fields:
        assert price is not None
        updated = replace(updated, price=price)
    if "stock" in fields:
        updated = replace(updated, stock=stock)
    if "is_active" in fields:
        assert is_active is not None
        updated = replace(updated, is_active=is_active)
    return updated


class ListPrivileges:
    """Каталог: student/teacher видят только активные, admin — все (У3)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> list[PrivilegeView]:
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
                required=CATALOGUE_VIEW_ROLES,
            )
            assert membership is not None
            active_only = membership.role is not UserRole.INSTITUTION_ADMIN
            privileges = await scope.market.list_privileges(active_only=active_only)
            return [_to_privilege_view(privilege) for privilege in privileges]


class CreatePrivilege:
    """Завести позицию каталога (П2: только admin)."""

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        title: str,
        description: str | None,
        price: int,
        stock: int | None,
        is_active: bool,
    ) -> PrivilegeView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            now = self._clock.now()
            privilege = Privilege(
                id=uuid.uuid4(),
                institution_id=institution_id,
                title=title,
                description=description,
                price=price,
                stock=stock,
                is_active=is_active,
                created_at=now,
                updated_at=now,
            )
            await scope.market.add_privilege(privilege)
            await uow.commit()
        return _to_privilege_view(privilege)


class UpdatePrivilege:
    """Изменить позицию каталога (П2: только admin, У11: partial PATCH).

    :raises PrivilegeNotFoundError: позиции нет в этом учреждении.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        privilege_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        fields: frozenset[str],
        title: str | None,
        description: str | None,
        price: int | None,
        stock: int | None,
        is_active: bool | None,
    ) -> PrivilegeView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            privilege = await scope.market.get_privilege(privilege_id)
            if privilege is None:
                raise PrivilegeNotFoundError
            updated = _apply_privilege_update(
                privilege,
                fields=fields,
                title=title,
                description=description,
                price=price,
                stock=stock,
                is_active=is_active,
            )
            updated = replace(updated, updated_at=self._clock.now())
            saved = await scope.market.update_privilege(updated)
            if saved is None:
                raise PrivilegeNotFoundError
            await uow.commit()
        return _to_privilege_view(saved)


def _purchase_matches(
    existing: Purchase,
    *,
    membership_id: uuid.UUID,
    privilege_id: uuid.UUID,
    price: int,
) -> bool:
    """Тот же по существу запрос — идемпотентный повтор, а не конфликт."""
    return (
        existing.membership_id == membership_id
        and existing.privilege_id == privilege_id
        and existing.price == price
    )


class CreatePurchase:
    """Купить привилегию (В2/M2) — только student (У1).

    Порядок проверок: доступ → ``operation_id`` → позиция и цена →
    баланс (план 07, раздел «Ч1»).

    :raises PrivilegeNotFoundError: позиции нет, она из другого
        учреждения или скрыта.
    :raises OutOfStockError: остаток исчерпан (В5/L2).
    :raises PriceChangedError: цена изменилась с момента, когда её видел
        покупатель (У5).
    :raises InsufficientBalanceError: баланса не хватает (П3).
    :raises OperationIdConflictError: ``operation_id`` уже занят другими
        параметрами (П4).
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        operation_id: uuid.UUID,
        privilege_id: uuid.UUID,
        expected_price: int,
    ) -> tuple[PurchaseView, bool]:
        """Вернуть (представление, создана ли запись именно сейчас)."""
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
                required=PURCHASE_ROLES,
            )
            assert membership is not None

            existing = await scope.market.get_purchase_by_operation_id(operation_id)
            if existing is not None:
                if not _purchase_matches(
                    existing,
                    membership_id=membership.id,
                    privilege_id=privilege_id,
                    price=expected_price,
                ):
                    raise OperationIdConflictError
                return (
                    await _to_purchase_view(scope, existing, with_member=False),
                    False,
                )

            try:
                purchase = await scope.market.purchase(
                    membership_id=membership.id,
                    privilege_id=privilege_id,
                    expected_price=expected_price,
                    operation_id=operation_id,
                    created_at=self._clock.now(),
                )
            except OperationIdConflictError:
                # Параллельный повтор — тот же исход, что при обычном
                # повторе (идемпотентность по построению, план 06 раздел 5).
                existing = await scope.market.get_purchase_by_operation_id(operation_id)
                if existing is None:
                    raise
                if not _purchase_matches(
                    existing,
                    membership_id=membership.id,
                    privilege_id=privilege_id,
                    price=expected_price,
                ):
                    raise OperationIdConflictError from None
                view = await _to_purchase_view(scope, existing, with_member=False)
                await uow.commit()
                return view, False

            view = await _to_purchase_view(scope, purchase, with_member=False)
            await uow.commit()
            return view, True


class ListMyPurchases:
    """Свои покупки — последние 50, только student (`GET /me/purchases`)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> list[PurchaseView]:
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
                required=PURCHASE_ROLES,
            )
            assert membership is not None
            purchases = await scope.market.list_my_purchases(
                membership.id, limit=RECENT_PURCHASES_LIMIT
            )
            return [
                await _to_purchase_view(scope, purchase, with_member=False)
                for purchase in purchases
            ]


class ListPurchases:
    """Покупки учреждения — только admin (`GET /purchases?status=&user_id=`).

    Без ``status`` — последние 50 всех статусов (раздел 9 плана,
    подтверждено владельцем); ``status=pending`` — без лимита (У8),
    остальные явные статусы — тоже последние 50.

    :raises MemberNotFoundError: ``user_id`` не найден в этом учреждении.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        status: PurchaseStatus | None,
        user_id: uuid.UUID | None,
    ) -> list[PurchaseView]:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            target_membership_id: uuid.UUID | None = None
            if user_id is not None:
                target = await scope.memberships.get_for_user(user_id)
                if target is None:
                    raise MemberNotFoundError
                target_membership_id = target.id
            limit = None if status is PurchaseStatus.PENDING else RECENT_PURCHASES_LIMIT
            purchases = await scope.market.list_purchases(
                status=status, membership_id=target_membership_id, limit=limit
            )
            return [
                await _to_purchase_view(scope, purchase, with_member=True)
                for purchase in purchases
            ]


class FulfilPurchase:
    """Отметить покупку выданной — только admin (У9: идемпотентно по статусу).

    :raises PurchaseNotFoundError: покупки нет в этом учреждении.
    :raises PurchaseAlreadyResolvedError: покупка уже отклонена.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        purchase_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> PurchaseView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor = await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            purchase = await scope.market.resolve_fulfil(
                purchase_id,
                resolved_by_membership_id=actor.id,
                now=self._clock.now(),
            )
            # До commit (риск 2 плана 07a): with_member читает членство —
            # RLS-таблицу, чей контекст истекает вместе с транзакцией.
            view = await _to_purchase_view(scope, purchase, with_member=True)
            await uow.commit()
        return view


class RejectPurchase:
    """Отклонить покупку — только admin: возврат валюты и остатка (В2/M2).

    :raises PurchaseNotFoundError: покупки нет в этом учреждении.
    :raises PurchaseAlreadyResolvedError: покупка уже выдана.
    """

    def __init__(self, uow: UnitOfWork, clock: Clock) -> None:
        self._uow = uow
        self._clock = clock

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        purchase_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> PurchaseView:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            actor = await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            purchase = await scope.market.resolve_reject(
                purchase_id,
                resolved_by_membership_id=actor.id,
                now=self._clock.now(),
                refund_operation_id=uuid.uuid4(),
            )
            view = await _to_purchase_view(scope, purchase, with_member=True)
            await uow.commit()
        return view
