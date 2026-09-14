"""Правило слоя ``business``: только stdlib и сам бизнес-слой.

Тест обходит AST каждого модуля ``app/business/**`` и падает на импорте
каркасов и соседних слоёв. Дисциплина здесь не подходит: раскладка
из плана этапа 2 (Р2/D1) прямо требует проверки тестом, а не обзором
кода на ревью.

Список запрещённых префиксов взят из плана этапа: ``fastapi``,
``fastapi_users``, ``starlette``, ``pydantic``, ``pydantic_settings``,
``sqlalchemy``, ``redis``, ``httpx``, ``app.api``, ``app.repositories``,
``app.auth``, ``app.core``. ``gamification_auth`` в списке нет — в
сервисе users бизнес-слой его не использует; когда понадобится, сюда
нужно будет добавить осознанное исключение с комментарием-причиной, как
это сделано в плане для ``jwt``/``token_claims`` у gamification.
"""

import ast
from pathlib import Path

import pytest

BUSINESS_ROOT = Path(__file__).parent.parent / "app" / "business"

FORBIDDEN_PREFIXES = (
    "fastapi",
    "fastapi_users",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "sqlalchemy",
    "redis",
    "httpx",
    "app.api",
    "app.repositories",
    "app.auth",
    "app.core",
)


def _business_modules() -> list[Path]:
    """Собрать все модули бизнес-слоя, включая ``__init__.py``."""
    return sorted(BUSINESS_ROOT.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> list[str]:
    """Вернуть имена модулей, импортируемых на верхнем уровне и внутри."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.append(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(
        module == prefix or module.startswith(f"{prefix}.")
        for prefix in FORBIDDEN_PREFIXES
    )


@pytest.mark.parametrize("path", _business_modules(), ids=lambda p: str(p))
def test_business_module_does_not_import_frameworks(path: Path) -> None:
    """Ни один модуль ``app/business/**`` не тянет каркасы или соседние слои."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = [module for module in _imported_modules(tree) if _is_forbidden(module)]

    assert forbidden == [], (
        f"{path} импортирует запрещённые для business модули: {forbidden}"
    )
