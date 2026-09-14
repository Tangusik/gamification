"""Общее для use case'ов преподавателей и учеников (Ч2а, Ч2в).

Обе роли показываются одной и той же формой ответа
(``{user_id, display_name, status, created_at, group_ids}``, В4/В5) и
обновляются одной и той же операцией — разница только в том, откуда
берётся ``group_ids`` (группы, которые ведёт преподаватель, или группы,
в которых состоит ученик).
"""

import uuid
from dataclasses import dataclass, replace
from datetime import datetime

from app.business.domain.entities import Membership
from app.business.domain.enums import MembershipStatus


@dataclass(frozen=True)
class MemberView:
    """Элемент списка преподавателей/учеников — форма ``MemberRead`` (Ч2)."""

    user_id: uuid.UUID
    display_name: str | None
    status: MembershipStatus
    created_at: datetime
    group_ids: list[uuid.UUID]


def apply_member_update(
    membership: Membership,
    *,
    display_name: str | None,
    status: MembershipStatus | None,
) -> Membership:
    """Вернуть членство с применёнными изменениями ``PATCH``.

    ``display_name`` и ``status`` меняются, только если переданы — ``None``
    здесь значит «поле не пришло в запросе», а не «стереть значение»:
    очистка заполненного имени через ``PATCH`` в этом этапе не входит в
    объём (минимальный вариант, см. базу знаний).
    """
    updated = membership
    if display_name is not None:
        updated = replace(updated, display_name=display_name)
    if status is not None:
        updated = replace(updated, status=status)
    return updated
