"""Эндпоинты маркета привилегий (план 07, Ч1): каталог и покупки.

Роутер голый: ``prefix``/``tags`` — в ``app/api/main_router.py``. Повтор
покупки с тем же ``operation_id`` и тем же телом отвечает 200 с уже
созданной записью вместо 201 — тот же приём, что и у валюты
(``app/api/external/currency.py``).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    get_create_privilege,
    get_create_purchase,
    get_fulfil_purchase,
    get_list_my_purchases,
    get_list_privileges,
    get_list_purchases,
    get_reject_purchase,
    get_update_privilege,
)
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.domain.enums import PurchaseStatus
from app.business.use_cases.market import (
    CreatePrivilege,
    CreatePurchase,
    FulfilPurchase,
    ListMyPurchases,
    ListPrivileges,
    ListPurchases,
    PrivilegeView,
    PurchaseView,
    RejectPurchase,
    UpdatePrivilege,
)
from app.schemas.market import (
    PrivilegeCreate,
    PrivilegeRead,
    PrivilegeUpdate,
    PurchaseCreate,
    PurchaseRead,
)

router = APIRouter()


def _to_privilege_read(view: PrivilegeView) -> PrivilegeRead:
    return PrivilegeRead(
        id=view.id,
        title=view.title,
        description=view.description,
        price=view.price,
        stock=view.stock,
        is_active=view.is_active,
    )


def _to_purchase_read(view: PurchaseView) -> PurchaseRead:
    return PurchaseRead(
        id=view.id,
        privilege_id=view.privilege_id,
        title=view.title,
        price=view.price,
        status=view.status,
        created_at=view.created_at,
        resolved_at=view.resolved_at,
        user_id=view.user_id,
        user_name=view.user_name,
    )


@router.get("/{institution_id:uuid}/privileges")
async def list_privileges(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListPrivileges, Depends(get_list_privileges)],
) -> list[PrivilegeRead]:
    """Каталог: student/teacher — только активные, admin — все (У3)."""
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return [_to_privilege_read(view) for view in views]


@router.post("/{institution_id:uuid}/privileges", status_code=status.HTTP_201_CREATED)
async def create_privilege(
    institution_id: uuid.UUID,
    payload: PrivilegeCreate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreatePrivilege, Depends(get_create_privilege)],
) -> PrivilegeRead:
    """Завести позицию каталога — только admin (П2)."""
    view = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        title=payload.title,
        description=payload.description,
        price=payload.price,
        stock=payload.stock,
        is_active=payload.is_active,
    )
    return _to_privilege_read(view)


@router.patch("/{institution_id:uuid}/privileges/{privilege_id:uuid}")
async def update_privilege(
    institution_id: uuid.UUID,
    privilege_id: uuid.UUID,
    payload: PrivilegeUpdate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[UpdatePrivilege, Depends(get_update_privilege)],
) -> PrivilegeRead:
    """Изменить позицию каталога — только admin (У11: поле не передано ≠ null)."""
    fields = frozenset(payload.model_fields_set)
    view = await use_case.execute(
        institution_id=institution_id,
        privilege_id=privilege_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        fields=fields,
        title=payload.title,
        description=payload.description,
        price=payload.price,
        stock=payload.stock,
        is_active=payload.is_active,
    )
    return _to_privilege_read(view)


@router.post("/{institution_id:uuid}/purchases", status_code=status.HTTP_201_CREATED)
async def create_purchase(
    institution_id: uuid.UUID,
    payload: PurchaseCreate,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreatePurchase, Depends(get_create_purchase)],
) -> PurchaseRead:
    """Купить привилегию — только student (В2/M2).

    Повтор того же ``operation_id`` с тем же телом отвечает 200 с уже
    созданной покупкой вместо повторного списания.
    """
    view, created = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        operation_id=payload.operation_id,
        privilege_id=payload.privilege_id,
        expected_price=payload.expected_price,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _to_purchase_read(view)


@router.get("/{institution_id:uuid}/me/purchases")
async def list_my_purchases(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListMyPurchases, Depends(get_list_my_purchases)],
) -> list[PurchaseRead]:
    """Свои покупки — последние 50, только student."""
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return [_to_purchase_read(view) for view in views]


@router.get("/{institution_id:uuid}/purchases")
async def list_purchases(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListPurchases, Depends(get_list_purchases)],
    status_filter: Annotated[PurchaseStatus | None, Query(alias="status")] = None,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[PurchaseRead]:
    """Покупки учреждения — только admin.

    Без ``status`` — последние 50 покупок всех статусов (раздел 9 плана);
    ``status=pending`` — без лимита (У8), остальные статусы — тоже
    последние 50.
    """
    views = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        status=status_filter,
        user_id=user_id,
    )
    return [_to_purchase_read(view) for view in views]


@router.post("/{institution_id:uuid}/purchases/{purchase_id:uuid}/fulfil")
async def fulfil_purchase(
    institution_id: uuid.UUID,
    purchase_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[FulfilPurchase, Depends(get_fulfil_purchase)],
) -> PurchaseRead:
    """Отметить покупку выданной — только admin, идемпотентно по статусу (У9)."""
    view = await use_case.execute(
        institution_id=institution_id,
        purchase_id=purchase_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return _to_purchase_read(view)


@router.post("/{institution_id:uuid}/purchases/{purchase_id:uuid}/reject")
async def reject_purchase(
    institution_id: uuid.UUID,
    purchase_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[RejectPurchase, Depends(get_reject_purchase)],
) -> PurchaseRead:
    """Отклонить покупку — только admin: возврат валюты и остатка (В2/M2)."""
    view = await use_case.execute(
        institution_id=institution_id,
        purchase_id=purchase_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return _to_purchase_read(view)
