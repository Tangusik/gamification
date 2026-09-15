"""Эндпоинты учреждений: создание, свои членства, переключение (раздел 6).

Роутер голый: ``prefix`` и ``tags`` задаются в ``app/api/main_router.py``.
Обработчики только разбирают запрос, зовут use case и собирают ответ —
правила живут в ``app.business`` (иначе, чем в users, где
``select_institution`` сам проверял статус членства).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import (
    get_create_institution,
    get_get_institution,
    get_list_my_institutions,
    get_switch_institution,
    get_update_institution,
)
from app.auth.actor import Actor
from app.auth.dependencies import get_current_actor
from app.business.domain.entities import Institution
from app.business.use_cases.context import SwitchInstitution
from app.business.use_cases.institution_settings import (
    GetInstitution,
    UpdateInstitution,
)
from app.business.use_cases.institutions import CreateInstitution, ListMyInstitutions
from app.schemas.institution import (
    ContextTokenResponse,
    InstitutionCreate,
    InstitutionCreated,
    InstitutionRead,
    InstitutionUpdate,
    MembershipRead,
)

router = APIRouter()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_institution(
    payload: InstitutionCreate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[CreateInstitution, Depends(get_create_institution)],
) -> InstitutionCreated:
    """Завести учреждение; создатель становится ``institution_admin`` (E1).

    Доступен любому аутентифицированному пользователю — контекст
    учреждения не нужен, его как раз ещё нет.
    """
    institution = await use_case.execute(
        name=payload.name, kind=payload.kind, created_by=actor.user_id
    )
    return InstitutionCreated(id=institution.id)


@router.get("")
async def list_my_institutions(
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[ListMyInstitutions, Depends(get_list_my_institutions)],
) -> list[MembershipRead]:
    """Свои членства — из чего клиенту выбирать (как ``GET /users/me/institutions``)."""
    views = await use_case.execute(user_id=actor.user_id)
    return [
        MembershipRead(
            institution_id=view.institution_id,
            name=view.name,
            kind=view.kind,
            role=view.role,
            status=view.status,
            currency_name=view.currency_name,
        )
        for view in views
    ]


@router.post("/{institution_id:uuid}/token")
async def switch_institution(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[SwitchInstitution, Depends(get_switch_institution)],
    response: Response,
) -> ContextTokenResponse:
    """Выпустить токен в контексте учреждения (раздел 4).

    Нет членства, оно неактивно или учреждения не существует — один и
    тот же ``NOT_A_MEMBER`` без обращения в users (раздел 4.1).
    """
    result = await use_case.execute(
        user_id=actor.user_id,
        institution_id=institution_id,
        subject_token=actor.raw_token,
    )
    # Токен не должен оседать в кешах между клиентом и сервисом.
    response.headers["Cache-Control"] = "no-store"
    return ContextTokenResponse(access_token=result.access_token)


def _to_read(institution: Institution) -> InstitutionRead:
    return InstitutionRead(
        id=institution.id,
        name=institution.name,
        kind=institution.kind,
        created_at=institution.created_at,
        currency_name=institution.currency_name,
    )


@router.get("/{institution_id:uuid}")
async def get_institution(
    institution_id: uuid.UUID,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[GetInstitution, Depends(get_get_institution)],
) -> InstitutionRead:
    """Показать учреждение (Ч2г, В7/S1: просмотр и переименование)."""
    institution = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
    )
    return _to_read(institution)


@router.patch("/{institution_id:uuid}")
async def update_institution(
    institution_id: uuid.UUID,
    payload: InstitutionUpdate,
    actor: Annotated[Actor, Depends(get_current_actor)],
    use_case: Annotated[UpdateInstitution, Depends(get_update_institution)],
) -> InstitutionRead:
    """Изменить настройки учреждения: имя и/или название валюты (Ч2г, В5).

    Непереданное поле не меняется (``model_fields_set``); значения,
    какие поля вообще пришли, — забота схемы и use case, обработчик их
    не интерпретирует.
    """
    fields = frozenset(payload.model_fields_set)
    institution = await use_case.execute(
        institution_id=institution_id,
        actor_user_id=actor.user_id,
        actor_institution_id=actor.institution_id,
        fields=fields,
        name=payload.name,
        currency_name=payload.currency_name,
    )
    return _to_read(institution)
