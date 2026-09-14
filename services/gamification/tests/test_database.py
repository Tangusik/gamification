"""Тест настроек движка SQLAlchemy: сокрытие параметров запросов."""

from app.repositories.database import create_engine


def test_engine_hides_parameters_by_default() -> None:
    """Токен приглашения — параметр запроса; при ``DBAPIError`` SQLAlchemy по
    умолчанию печатает ``[parameters: (...)]`` в текст ошибки, и он уходит в
    лог uvicorn. ``hide_parameters=True`` должен быть включён без явной
    передачи аргумента.
    """
    engine = create_engine("postgresql+asyncpg://user:pw@localhost/db")

    # AsyncEngine — обёртка: атрибут живёт на её внутреннем sync_engine.
    assert engine.sync_engine.hide_parameters is True


def test_engine_allows_explicit_override() -> None:
    """Явный аргумент не перебивается значением по умолчанию."""
    engine = create_engine(
        "postgresql+asyncpg://user:pw@localhost/db", hide_parameters=False
    )

    assert engine.sync_engine.hide_parameters is False
