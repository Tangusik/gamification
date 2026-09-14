"""Словарь ошибок доступа: роли, членство, контекст учреждения.

Перенесён из ``services/users/app/domain/access_errors.py`` (раздел 1
плана) — коды часть публичного контракта, по ним ветвятся фронтенд,
мобильное приложение и соседние сервисы.

Правила словаря:

* код — стабильная строка, он не локализуется;
* код не переиспользуется под новым смыслом и не удаляется молча;
* HTTP-статуса здесь нет — домен про HTTP не знает, перевод живёт в
  ``app/core/exceptions.py``.
"""

from typing import ClassVar

from app.business.domain.enums import UserRole
from app.business.domain.errors import DomainError


class AccessError(DomainError):
    """Базовая ошибка доступа. ``code`` — то, что увидит клиент."""

    code: ClassVar[str]


class InvalidRoleError(AccessError):
    """Переданной роли не существует в системе."""

    code = "INVALID_ROLE"

    def __init__(self, value: str) -> None:
        super().__init__(f"Неизвестная роль: {value!r}")


class InsufficientRoleError(AccessError):
    """Роль членства не входит в набор, требуемый эндпоинтом.

    Требуемые роли и фактическая сохраняются для лога: в ответ уходит
    только код, чтобы не подсказывать перебором устройство прав.
    """

    code = "INSUFFICIENT_ROLE"

    def __init__(self, required: tuple[UserRole, ...], actual: UserRole) -> None:
        self.required = required
        self.actual = actual
        allowed = ", ".join(role.value for role in required)
        super().__init__(
            f"Требуется роль из [{allowed}], у пользователя {actual.value}"
        )


class NotAMemberError(AccessError):
    """Пользователь не состоит в учреждении, к которому обращается.

    Нет членства, членство неактивно или учреждения не существует —
    во всех трёх случаях один и тот же код: различать нельзя, иначе по
    разнице ответов перебором восстанавливается список учреждений и
    состав их участников.
    """

    code = "NOT_A_MEMBER"


class InstitutionContextRequiredError(AccessError):
    """Эндпоинт учреждения, а в токене нет активного учреждения."""

    code = "INSTITUTION_CONTEXT_REQUIRED"


class RoleAssignmentForbiddenError(AccessError):
    """Вызывающий не вправе выдавать эту роль."""

    code = "ROLE_ASSIGNMENT_FORBIDDEN"


class MembershipSuspendedError(AccessError):
    """Приостановленное членство пытаются использовать (F7).

    Реактивации нет: исключённый ученик не может вернуться по любой
    групповой ссылке. Отдельно от ``NotAMemberError`` — там членства нет
    вовсе, здесь оно есть, но временно не даёт доступа.
    """

    code = "MEMBERSHIP_SUSPENDED"


class InvitationInvalidError(AccessError):
    """Приглашение не найдено, отозвано или исчерпано (раздел 5).

    Один код на все три случая: различать их публично значило бы дать
    оракул для перебора токенов приглашений.
    """

    code = "INVITATION_INVALID"
