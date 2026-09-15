"""Словарь кодов внутреннего API gamification.

Отдельное пространство от словаря ошибок доступа
(``app/business/domain/access_errors.py``, конечные пользователи) и от
одноимённого словаря ``services/users/app/business/domain/internal_errors.py`` —
ошибка внутреннего вызова не то же самое, что ошибка конечного
пользователя (``.claude/knowledge/08-api-contract.md``). Заведён вместе
с первым внутренним эндпоинтом gamification —
``POST /internal/memberships/resolve`` (план `.claude/plans/10-refresh.md`,
Ч2), которым пользуется users при refresh для восстановления контекста
учреждения.

* ``SERVICE_AUTH_FAILED`` — вызывающий сервис (users) не предъявил
  верный служебный секрет. Авария на его стороне или атака, а не отказ
  в правах конечного пользователя.
* ``MEMBERSHIP_NOT_ACTIVE`` — один код на три случая: членства нет, оно
  приостановлено, учреждения не существует. Детализация не нужна ни
  одному законному вызывающему и была бы оракулом для перебора состава
  учреждений (тот же принцип, что у ``NOT_A_MEMBER`` в
  ``access_errors.py``).

Правила словаря те же, что и у остальных: код — стабильная строка, не
локализуется и не переиспользуется под новым смыслом; HTTP-статус в
домене не хранится, перевод — задача ``app/core/exceptions.py``.
"""

from typing import ClassVar

from app.business.domain.errors import DomainError


class InternalApiError(DomainError):
    """Базовая ошибка внутреннего API gamification.

    ``code`` — то, что уходит вызывающему сервису в ``detail``.
    """

    code: ClassVar[str]


class ServiceAuthFailedError(InternalApiError):
    """Вызывающий сервис не предъявил верный служебный секрет."""

    code = "SERVICE_AUTH_FAILED"


class MembershipNotActiveError(InternalApiError):
    """Членства нет, оно приостановлено, либо учреждения не существует.

    Один код на все три причины — по тому же принципу, что и у
    ``NOT_A_MEMBER``/``MemberNotFoundError``: разница в ответах стала бы
    оракулом для перебора учреждений и их состава.
    """

    code = "MEMBERSHIP_NOT_ACTIVE"
