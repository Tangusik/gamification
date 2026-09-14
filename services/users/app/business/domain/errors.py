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
