"""Правило слоя: ``app/business/**`` не импортирует ничего, кроме stdlib.

Тест обходит AST модулей слоя и падает на запрещённом импорте — линтер
импортов не заводится ради одного правила (раздел 2 плана).
"""

import ast
from pathlib import Path

FORBIDDEN_ROOTS = {
    "fastapi",
    "starlette",
    "pydantic",
    "sqlalchemy",
    "redis",
    "httpx",
    "gamification_auth",
    "app.api",
    "app.repositories",
    "app.clients",
    "app.auth",
}

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BUSINESS_DIR = SERVICE_ROOT / "app" / "business"


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _is_forbidden(module: str) -> bool:
    return any(
        module == root or module.startswith(root + ".") for root in FORBIDDEN_ROOTS
    )


def test_business_layer_has_no_forbidden_imports() -> None:
    violations: list[str] = []
    for path in sorted(BUSINESS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if _is_forbidden(module):
                violations.append(f"{path.relative_to(SERVICE_ROOT)}: {module}")

    assert not violations, (
        "Слой business импортирует запрещённые модули:\n" + "\n".join(violations)
    )


def test_business_dir_is_not_empty() -> None:
    """Страховка от ложноположительного зелёного теста на пустой папке."""
    assert list(BUSINESS_DIR.rglob("*.py"))
