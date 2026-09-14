"""Словарь кодов внутреннего API: выпуск токена в контексте учреждения.

Отдельное пространство от словаря ошибок доступа
(``app/business/domain/access_errors.py`` — он уехал в gamification
вместе с членствами): ошибка внутреннего вызова не то же самое, что
ошибка конечного пользователя (см. ``.claude/knowledge/08-api-contract.md``).
Коды, относящиеся к ``POST /internal/tokens/institution-context``:

* ``SERVICE_AUTH_FAILED`` — вызывающий сервис не предъявил верный
  служебный секрет. Это авария на стороне gamification (или атака), а
  не отказ в правах конкретному пользователю.
* ``SUBJECT_TOKEN_REJECTED`` — предъявленный gamification
  ``subject_token`` не прошёл ни одну из проверок users (подпись, срок,
  отзыв, активность пользователя) либо остаток его жизни истёк.

Коды, относящиеся к ``POST /internal/users`` (план
``.claude/plans/05-admin-features.md``, В1/Ч1):

* ``USER_ALREADY_EXISTS`` — email уже зарегистрирован. Отдельный код от
  доменного ``USER_ALREADY_EXISTS`` в ``errors.py`` (там он для
  публичной регистрации): пространства кодов внутреннего API и
  конечного пользователя разные по определению модуля, даже когда
  строка совпала по смыслу.
* ``PASSWORD_REJECTED`` — пароль не прошёл ``UserManager.validate_password``
  (сейчас — минимальная длина).

Правила словаря те же, что и у ``access_errors``: код — стабильная
строка, не локализуется и не переиспользуется под новым смыслом;
HTTP-статус в домене не хранится, перевод — задача
``app/core/exceptions.py``.
"""

from typing import ClassVar

from app.business.domain.errors import DomainError


class InternalApiError(DomainError):
    """Базовая ошибка внутреннего API.

    ``code`` — то, что уходит вызывающему сервису в ``detail``.
    """

    code: ClassVar[str]


class ServiceAuthFailedError(InternalApiError):
    """Вызывающий сервис не предъявил верный служебный секрет."""

    code = "SERVICE_AUTH_FAILED"


class SubjectTokenRejectedError(InternalApiError):
    """Предъявленный ``subject_token`` не прошёл проверку users.

    Общий код на «невалиден», «истёк», «отозван» и «пользователь не
    существует или неактивен» — по тем же соображениям, что и у
    ``NOT_A_MEMBER``: детализация здесь не нужна ни одному законному
    вызывающему.
    """

    code = "SUBJECT_TOKEN_REJECTED"


class UserAlreadyExistsError(InternalApiError):
    """Аккаунт с таким email уже существует (``POST /internal/users``).

    Совпадает по имени с доменной ``errors.UserAlreadyExistsError`` —
    это разные классы в разных пространствах кодов, импортирующий код
    обязан различать их по модулю (алиас при одновременном импорте).
    """

    code = "USER_ALREADY_EXISTS"


class PasswordRejectedError(InternalApiError):
    """Пароль не прошёл политику паролей (``POST /internal/users``)."""

    code = "PASSWORD_REJECTED"
