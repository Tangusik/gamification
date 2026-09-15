"""Доменные исключения сервиса users.

Слой не знает про HTTP: трансляция в коды ответов — задача слоя API.
Сообщения намеренно не содержат email и других персональных данных,
поскольку попадают в логи.
"""


class DomainError(Exception):
    """Базовое исключение доменного слоя."""


class UserAlreadyExistsError(DomainError):
    """Пользователь с таким email уже зарегистрирован."""

    def __init__(self) -> None:
        super().__init__("Пользователь с таким email уже существует")


class UserNotFoundError(DomainError):
    """Запрошенный пользователь не найден."""

    def __init__(self) -> None:
        super().__init__("Пользователь не найден")


class RefreshTokenInvalidError(DomainError):
    """Предъявленный refresh-токен отклонён (план 10-refresh, раздел 3).

    Единый код на все причины: нет токена, неизвестен, истёк, отозван,
    повтор, пользователь неактивен, не тот ``client``. Разные коды стали
    бы оракулом для перебора — детализация не идёт дальше лога.
    """

    def __init__(self) -> None:
        super().__init__("Refresh-токен недействителен")


class CsrfCheckFailedError(DomainError):
    """Cookie-путь без обязательного заголовка ``X-Requested-With`` (У6)."""

    def __init__(self) -> None:
        super().__init__("Отсутствует заголовок X-Requested-With")


class MembershipNotActiveError(DomainError):
    """Gamification ответила 404: членства нет, оно приостановлено, либо
    учреждения не существует (один код на все три случая, раздел 3)."""

    def __init__(self) -> None:
        super().__init__("Членство не активно")


class MembershipCheckUnavailableError(DomainError):
    """Gamification недоступна: сеть, таймаут, 5xx, 401 или 422 (вопрос 2 = А).

    Перехватывается внутри use case refresh и не долетает до HTTP-слоя:
    ответом остаётся access без контекста, а не ошибка (вопрос 2 = А).
    """

    def __init__(self) -> None:
        super().__init__("Проверка членства недоступна")
