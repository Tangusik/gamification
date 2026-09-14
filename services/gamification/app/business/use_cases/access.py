"""Общая проверка доступа для use case'ов администратора учреждения (Ч2).

Одна функция поверх ``require_institution_context`` + ``check_role`` —
каждый новый use case функций администратора вызывает именно её, а не
собирает проверки заново.
"""

import uuid

from app.business.domain.entities import Membership
from app.business.domain.enums import UserRole
from app.business.domain.errors import MemberNotFoundError
from app.business.domain.policies import check_role, require_institution_context
from app.business.ports import InstitutionScope

# Все эндпоинты этого этапа доступны только institution_admin (умолчания
# плана): преподаватели и ученики новых экранов не получают.
ADMIN_ROLES = (UserRole.INSTITUTION_ADMIN,)

# Валюта и видимость учеников/групп (план 06, В1/А2, У7): преподаватель и
# админ, а не только админ.
STUDENT_CURRENCY_ROLES = (UserRole.TEACHER, UserRole.INSTITUTION_ADMIN)


async def require_institution_admin(
    *,
    scope: InstitutionScope,
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_institution_id: uuid.UUID | None,
) -> Membership:
    """Убедиться, что вызывающий — активный ``institution_admin`` этого
    учреждения, и вернуть его собственное членство.

    :raises InstitutionContextRequiredError: контекст токена не совпадает
        с учреждением из пути.
    :raises NotAMemberError: нет активного членства в этом учреждении.
    :raises InsufficientRoleError: роль членства не ``institution_admin``.
    """
    require_institution_context(
        path_institution_id=institution_id,
        token_institution_id=actor_institution_id,
    )
    membership = await scope.memberships.get_for_user(actor_user_id)
    check_role(
        active_institution_id=actor_institution_id,
        membership=membership,
        required=ADMIN_ROLES,
    )
    assert membership is not None  # check_role уже это гарантировал
    return membership


async def require_admin_or_teacher(
    *,
    scope: InstitutionScope,
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_institution_id: uuid.UUID | None,
) -> Membership:
    """Убедиться, что вызывающий — активный ``teacher`` или
    ``institution_admin`` этого учреждения, и вернуть его членство.

    Видимость учеников и групп для преподавателя (У7) и доступ к валюте
    (В1/А2): преподаватель видит только своих, админ — всё учреждение —
    решает вызывающий use case по роли возвращённого членства.

    :raises InstitutionContextRequiredError: контекст токена не совпадает
        с учреждением из пути.
    :raises NotAMemberError: нет активного членства в этом учреждении.
    :raises InsufficientRoleError: роль членства не входит в набор.
    """
    require_institution_context(
        path_institution_id=institution_id,
        token_institution_id=actor_institution_id,
    )
    membership = await scope.memberships.get_for_user(actor_user_id)
    check_role(
        active_institution_id=actor_institution_id,
        membership=membership,
        required=STUDENT_CURRENCY_ROLES,
    )
    assert membership is not None  # check_role уже это гарантировал
    return membership


async def require_student_access(
    *,
    scope: InstitutionScope,
    institution_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_institution_id: uuid.UUID | None,
    target_user_id: uuid.UUID,
) -> tuple[Membership, Membership]:
    """Проверить доступ teacher/admin к валюте конкретного ученика (В1/А2).

    Админ видит любого ученика учреждения; преподаватель — только
    учеников своих групп, пересечением ``list_group_ids_for_teacher`` и
    ``list_group_ids_for_student`` («доступ преподавателя», раздел 2
    плана 06). Возвращает пару (членство актора, членство ученика).

    :raises MemberNotFoundError: цели нет, она не ученик, из другого
        учреждения или (для преподавателя) вне его групп — один код на
        все случаи, тот же принцип, что и у ``_GroupMembershipUseCase``.
    """
    actor = await require_admin_or_teacher(
        scope=scope,
        institution_id=institution_id,
        actor_user_id=actor_user_id,
        actor_institution_id=actor_institution_id,
    )
    student = await scope.memberships.get_for_user(target_user_id)
    if student is None or student.role is not UserRole.STUDENT:
        raise MemberNotFoundError
    if actor.role is UserRole.TEACHER:
        teacher_group_ids = set(await scope.groups.list_group_ids_for_teacher(actor.id))
        student_group_ids = set(
            await scope.groups.list_group_ids_for_student(student.id)
        )
        if not (teacher_group_ids & student_group_ids):
            raise MemberNotFoundError
    return actor, student
