"""Тест полноты словаря ошибок доступа (раздел 1 и 6 плана).

Коды — часть публичного контракта; тест не даёт завести новый код или
поменять существующий молча.
"""

from app.business.domain.access_errors import (
    AccessError,
    InstitutionContextRequiredError,
    InsufficientRoleError,
    InvalidRoleError,
    InvitationInvalidError,
    MembershipSuspendedError,
    NotAMemberError,
    RoleAssignmentForbiddenError,
)
from app.core.exceptions import access_error_status

EXPECTED_CATALOGUE = {
    InvalidRoleError: ("INVALID_ROLE", 400),
    InsufficientRoleError: ("INSUFFICIENT_ROLE", 403),
    NotAMemberError: ("NOT_A_MEMBER", 403),
    InstitutionContextRequiredError: ("INSTITUTION_CONTEXT_REQUIRED", 403),
    RoleAssignmentForbiddenError: ("ROLE_ASSIGNMENT_FORBIDDEN", 403),
    MembershipSuspendedError: ("MEMBERSHIP_SUSPENDED", 403),
    InvitationInvalidError: ("INVITATION_INVALID", 404),
}


def _all_access_errors() -> set[type[AccessError]]:
    found: set[type[AccessError]] = set()
    queue = [AccessError]
    while queue:
        for subclass in queue.pop().__subclasses__():
            found.add(subclass)
            queue.append(subclass)
    return found


def test_catalogue_is_complete() -> None:
    assert _all_access_errors() == set(EXPECTED_CATALOGUE)


def test_codes_and_statuses() -> None:
    for error_class, (code, status) in EXPECTED_CATALOGUE.items():
        assert error_class.code == code
        assert access_error_status(error_class) == status


def test_codes_are_unique() -> None:
    codes = [code for code, _ in EXPECTED_CATALOGUE.values()]
    assert len(codes) == len(set(codes))
