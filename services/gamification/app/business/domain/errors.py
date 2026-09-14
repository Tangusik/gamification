"""Доменные исключения сервиса gamification, кроме ошибок доступа.

Слой не знает про HTTP: перевод в коды ответов — задача
``app/core/exceptions.py``. Сообщения не содержат идентификаторов
учреждений и токенов — они попадают в логи.
"""


class DomainError(Exception):
    """Базовое исключение бизнес-слоя."""


class MembershipAlreadyExistsError(DomainError):
    """У пользователя уже есть членство в этом учреждении.

    Пара «пользователь ↔ учреждение» уникальна: второе членство сделало
    бы выбор роли неоднозначным. Ограничение держит схема хранилища
    (``UNIQUE (user_id, institution_id)``), а не проверка в коде.
    """

    def __init__(self) -> None:
        super().__init__("Членство в этом учреждении уже существует")


class TokenIssuerUnavailableError(DomainError):
    """Users недоступен, не ответил вовремя или отверг служебный секрет.

    Соответствует 503 ``TOKEN_ISSUER_UNAVAILABLE`` клиенту (раздел 4.2 и
    4.6): и сетевая недоступность, и отказ по служебной аутентификации
    (401 ``SERVICE_AUTH_FAILED`` от users) дают клиенту одно и то же —
    отказ в правах вызывающего users клиенту не касается.
    """

    def __init__(self) -> None:
        super().__init__("Выпуск токена в контексте учреждения временно недоступен")


class SubjectTokenRejectedError(DomainError):
    """Users отверг предъявленный токен пользователя (403 из раздела 4.2).

    Транслируется клиенту как обычный 401: токен и так пора обновить
    через логин, отдельный код здесь не нужен.
    """

    def __init__(self) -> None:
        super().__init__("Предъявленный токен отклонён сервисом users")


class TokenIssuerContractError(DomainError):
    """Users ответил телом не по контракту (422) — дефект вызывающего.

    Отличается от ``TokenIssuerUnavailableError`` тем, что повтор
    запроса не поможет: это не временная недоступность, а расхождение
    контракта самого gamification.
    """

    def __init__(self) -> None:
        super().__init__("Нарушен контракт внутреннего выпуска токена users")


class EmailAlreadyRegisteredError(DomainError):
    """Users уже знает такой email (409 ``USER_ALREADY_EXISTS`` из плана В2/B3).

    Аккаунт не создаётся и членство не заводится (риск 1 плана).
    """

    def __init__(self) -> None:
        super().__init__("Пользователь с таким email уже зарегистрирован в users")


class InvalidPasswordError(DomainError):
    """Users отверг пароль (400 ``PASSWORD_REJECTED``) — например, короче
    минимальной длины.
    """

    def __init__(self) -> None:
        super().__init__("Users отклонил пароль как не удовлетворяющий требованиям")


class MemberNotFoundError(DomainError):
    """Члена с такой ролью нет в этом учреждении.

    Один код на «члена нет», «член из другого учреждения» и «у члена
    другая роль» (например, преподаватель в ``/students``) — иначе ответ
    выдавал бы состав и структуру ролей учреждения (раздел «Умолчания»).
    """

    def __init__(self) -> None:
        super().__init__("Член с ожидаемой ролью не найден в этом учреждении")


class GroupNotFoundError(DomainError):
    """Группы с таким идентификатором нет в этом учреждении."""

    def __init__(self) -> None:
        super().__init__("Группа не найдена в этом учреждении")


class GroupNameTakenError(DomainError):
    """Имя группы уже занято в учреждении без учёта регистра.

    Ограничение держит функциональный уникальный индекс в БД
    (``lower(name)``), а не предварительная проверка — та не защищает от
    гонки (тот же принцип, что и у ``MembershipAlreadyExistsError``).
    """

    def __init__(self) -> None:
        super().__init__("Имя группы уже занято в этом учреждении")


class UsersUnavailableError(DomainError):
    """Users недоступен, не ответил вовремя или отверг служебный секрет
    при создании аккаунта преподавателя (раздел «Ч2» плана).
    """

    def __init__(self) -> None:
        super().__init__("Создание аккаунта в users временно недоступно")


class UsersContractError(DomainError):
    """Users ответил созданием аккаунта не по контракту (422) — дефект
    вызывающего, повтор не поможет.
    """

    def __init__(self) -> None:
        super().__init__("Нарушен контракт внутреннего создания аккаунта users")


class StudentSuspendedError(DomainError):
    """Ученик приостановлен — ручное начисление недоступно (У6).

    Сторно приостановленному ученику разрешено (это исправление, а не
    начисление, В3/E2) — эта ошибка относится только к созданию нового
    начисления.
    """

    def __init__(self) -> None:
        super().__init__("Ученик приостановлен, начисление недоступно")


class OperationIdConflictError(DomainError):
    """``operation_id`` уже использован с другими параметрами (В4/I1).

    Пространство ``operation_id`` общее для начислений и сторно в
    пределах учреждения (``UNIQUE(institution_id, operation_id)``).
    Повтор с тем же телом на ту же цель — не эта ошибка, а идемпотентный
    200 с уже созданной записью.
    """

    def __init__(self) -> None:
        super().__init__("operation_id уже использован с другими параметрами")


class TransactionNotFoundError(DomainError):
    """Операции нет в этом учреждении, она из другого учреждения или это
    попытка сторнировать уже сторно-запись (В3/E2) — один код на все три
    случая, тот же принцип, что у ``MemberNotFoundError``.
    """

    def __init__(self) -> None:
        super().__init__("Операция не найдена в этом учреждении")


class TransactionAlreadyReversedError(DomainError):
    """Операция уже сторнирована другой записью (``UNIQUE(reverses_id)``,
    В3/E2). Гонку двух параллельных сторно одной операции решает это же
    ограничение — проигравший получает эту ошибку.
    """

    def __init__(self) -> None:
        super().__init__("Операция уже сторнирована")


class InsufficientBalanceError(DomainError):
    """Баланса не хватает на списание (план 07, П3).

    Общая ошибка для покупки и для сторно, которое увело бы баланс в
    минус (В4/RV1): второй рубеж — ``CHECK (balance >= 0)`` на
    ``currency_balances``, переводится из SQLSTATE ``23514``.
    """

    def __init__(self) -> None:
        super().__init__("Баланса не хватает для этой операции")


class PrivilegeNotFoundError(DomainError):
    """Позиции каталога нет в этом учреждении, она скрыта (``is_active
    = False``) или относится к другому учреждению (план 07, Ч1) — один
    код на все случаи, тот же принцип, что у ``MemberNotFoundError``.
    """

    def __init__(self) -> None:
        super().__init__("Позиция каталога не найдена в этом учреждении")


class OutOfStockError(DomainError):
    """Позиция активна, но остаток исчерпан (В5/L2)."""

    def __init__(self) -> None:
        super().__init__("Остаток позиции исчерпан")


class PriceChangedError(DomainError):
    """Цена позиции изменилась с момента, когда её видел покупатель (У5)."""

    def __init__(self) -> None:
        super().__init__("Цена позиции изменилась, подтвердите покупку заново")


class PurchaseNotFoundError(DomainError):
    """Покупки нет в этом учреждении или она относится к другому (план 07)."""

    def __init__(self) -> None:
        super().__init__("Покупка не найдена в этом учреждении")


class PurchaseAlreadyResolvedError(DomainError):
    """Покупка уже решена (``fulfilled``/``rejected``) с другим исходом,
    чем запрошенное действие (У9): выдать после отказа или наоборот.
    """

    def __init__(self) -> None:
        super().__init__("Покупка уже решена с другим исходом")


class ConcurrentUpdateError(DomainError):
    """БД сообщила дедлок (``40P01``) или serialization failure (``40001``).

    Оба SQLSTATE означают, что транзакция проиграла гонку за блокировки
    другой параллельной транзакции и была отменена самой PostgreSQL —
    данные не повреждены, но операцию нужно просто повторить. Перевод
    делает ``UnitOfWork`` (``app/repositories/uow.py``), единственная
    точка, через которую проходит любая транзакция сервиса.
    """

    def __init__(self) -> None:
        super().__init__("Конкурентное изменение данных, повторите запрос")
