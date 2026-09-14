"""Ролевые проверки доступа: чистые решения без HTTP и хранилища."""

import uuid

from app.business.domain.access_errors import (
    InstitutionContextRequiredError,
    InsufficientRoleError,
    NotAMemberError,
)
from app.business.domain.entities import Membership
from app.business.domain.enums import MembershipStatus, UserRole


def check_role(
    *,
    active_institution_id: uuid.UUID | None,
    membership: Membership | None,
    required: tuple[UserRole, ...],
) -> None:
    """Пропустить актора к ресурсу учреждения или бросить ошибку доступа.

    В отличие от users, здесь нет ветки ``is_superuser`` — этого флага
    gamification не видит вовсе (в токене его нет), поэтому обхода для
    владельца инсталляции не существует.

    Порядок проверок:

    1. Нет учреждения в токене — ``INSTITUTION_CONTEXT_REQUIRED``.
    2. Нет членства или оно не ``ACTIVE`` — ``NOT_A_MEMBER``.
    3. Роль членства не в требуемом наборе — ``INSUFFICIENT_ROLE``.
    """
    if active_institution_id is None:
        raise InstitutionContextRequiredError
    if membership is None or membership.status is not MembershipStatus.ACTIVE:
        raise NotAMemberError
    if membership.role not in required:
        raise InsufficientRoleError(required=required, actual=membership.role)


def require_institution_context(
    *, path_institution_id: uuid.UUID, token_institution_id: uuid.UUID | None
) -> None:
    """Проверить, что контекст токена совпадает с учреждением из пути (G1).

    Не используется эндпоинтами этого этапа: ``POST``/``GET
    /institutions`` и ``.../token`` контекста не требуют. Заведена уже
    сейчас, чтобы приглашения (этап 4, операции вида
    ``/institutions/{id}/invitations``) взяли её готовой.
    """
    if token_institution_id is None or token_institution_id != path_institution_id:
        raise InstitutionContextRequiredError
