"""Эндпоинты валюты (Ч1 плана 06): баланс, история, начисление, сторно.

Роутер голый: ``prefix``/``tags`` — в ``app/api/main_router.py``. Повтор
с тем же ``operation_id`` и тем же телом отвечает 200 с уже созданной
записью вместо 201/500 — обработчик переключает код ответа по флагу
``created`` из use case (раздел «Контракт» плана).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    get_create_accrual,
    get_create_reversal,
    get_get_my_currency,
    get_get_student_currency,
)
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.use_cases.currency import (
    CreateAccrual,
    CreateReversal,
    CurrencyAccountView,
    CurrencyTransactionView,
    GetMyCurrency,
    GetStudentCurrency,
)
from app.schemas.currency import (
    CurrencyAccountRead,
    CurrencyAccrualCreate,
    CurrencyReversalCreate,
    CurrencyTransactionRead,
)

router = APIRouter()


def _to_transaction_read(view: CurrencyTransactionView) -> CurrencyTransactionRead:
    return CurrencyTransactionRead(
        id=view.id,
        kind=view.kind,
        amount=view.amount,
        comment=view.comment,
        created_by_name=view.created_by_name,
        created_by_role=view.created_by_role,
        created_at=view.created_at,
        reverses_id=view.reverses_id,
    )


def _to_account_read(view: CurrencyAccountView) -> CurrencyAccountRead:
    return CurrencyAccountRead(
        balance=view.balance,
        transactions=[_to_transaction_read(tx) for tx in view.transactions],
    )


@router.get("/{institution_id:uuid}/me/currency")
async def get_my_currency(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[GetMyCurrency, Depends(get_get_my_currency)],
) -> CurrencyAccountRead:
    """Свой баланс и история — только ``student``."""
    view = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return _to_account_read(view)


@router.get("/{institution_id:uuid}/students/{user_id:uuid}/currency-transactions")
async def get_student_currency(
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[GetStudentCurrency, Depends(get_get_student_currency)],
) -> CurrencyAccountRead:
    """Баланс и история ученика — teacher и admin, только свои ученики."""
    view = await use_case.execute(
        institution_id=institution_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return _to_account_read(view)


@router.post(
    "/{institution_id:uuid}/students/{user_id:uuid}/currency-transactions",
    status_code=status.HTTP_201_CREATED,
)
async def create_accrual(
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: CurrencyAccrualCreate,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateAccrual, Depends(get_create_accrual)],
) -> CurrencyTransactionRead:
    """Ручное начисление — teacher и admin, только свои ученики (В2/C2).

    Повтор того же ``operation_id`` с тем же телом на ту же цель отвечает
    200 с уже созданной записью, а не повторяет начисление.
    """
    view, created = await use_case.execute(
        institution_id=institution_id,
        target_user_id=user_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        operation_id=payload.operation_id,
        amount=payload.amount,
        comment=payload.comment,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _to_transaction_read(view)


@router.post(
    "/{institution_id:uuid}/currency-transactions/{transaction_id:uuid}/reversal",
    status_code=status.HTTP_201_CREATED,
)
async def create_reversal(
    institution_id: uuid.UUID,
    transaction_id: uuid.UUID,
    payload: CurrencyReversalCreate,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateReversal, Depends(get_create_reversal)],
) -> CurrencyTransactionRead:
    """Сторно ручного начисления — только admin (В3/E2)."""
    view, created = await use_case.execute(
        institution_id=institution_id,
        transaction_id=transaction_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        operation_id=payload.operation_id,
    )
    if not created:
        response.status_code = status.HTTP_200_OK
    return _to_transaction_read(view)
