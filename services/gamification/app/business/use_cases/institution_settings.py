"""Use case'ы настроек учреждения (Ч2г, В7/S1): просмотр и переименование.

Тип (``kind``) только показывается — смена типа вне объёма этого этапа.
"""

import uuid
from dataclasses import replace

from app.business.domain.entities import Institution
from app.business.ports import UnitOfWork
from app.business.use_cases.access import require_institution_admin


class GetInstitution:
    """Показать учреждение (Ч2г)."""

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
    ) -> Institution:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            institution = await uow.institutions.get(institution_id)
        # Активное членство в учреждении гарантирует, что оно существует
        # (FK ``ON DELETE CASCADE`` не оставляет членств без учреждения).
        assert institution is not None
        return institution


class UpdateInstitution:
    """Изменить настройки учреждения: имя и/или название валюты (Ч2г, В5).

    Частичное обновление — та же схема, что у ``PATCH /privileges``:
    ``fields`` (``model_fields_set`` схемы) говорит, какие поля вообще
    пришли в теле, отсутствие имени в наборе значит «не менять», а не
    «сбросить». ``currency_name`` умеет обнуляться явным ``null``
    (``fields`` содержит имя, значение ``None``); ``name`` — нет, это
    гарантирует схема.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self._uow = uow

    async def execute(
        self,
        *,
        institution_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_institution_id: uuid.UUID | None,
        fields: frozenset[str],
        name: str | None,
        currency_name: str | None,
    ) -> Institution:
        async with self._uow as uow:
            scope = await uow.for_institution(institution_id)
            await require_institution_admin(
                scope=scope,
                institution_id=institution_id,
                actor_user_id=actor_user_id,
                actor_institution_id=actor_institution_id,
            )
            institution = await uow.institutions.get(institution_id)
            assert institution is not None
            updated = institution
            if "name" in fields:
                assert name is not None
                updated = replace(updated, name=name)
            if "currency_name" in fields:
                updated = replace(updated, currency_name=currency_name)
            await uow.institutions.update(updated)
            await uow.commit()
        return updated
