"""Health-эндпоинты сервиса: liveness и readiness.

Роутер голый: ``prefix`` и ``tags`` задаются в ``app/api/main_router.py``,
чтобы вся карта адресов сервиса читалась из одного файла.
"""

from fastapi import APIRouter, Request, Response, status

from app.api.deps import probe_database, probe_denylist

router = APIRouter()

# Значения в ``checks``: словарь читают люди и дашборды, поэтому статус
# словом, а не булевым.
_OK = "ok"
_UNAVAILABLE = "unavailable"


@router.get("/health")
async def liveness() -> dict[str, str]:
    """Liveness-проба: отвечает всегда, не обращается к зависимостям."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict[str, object]:
    """Readiness-проба: агрегирует состояние внешних зависимостей.

    Проверки складываются в ``checks`` как ``имя -> статус``; форма
    ответа под это и проектировалась и при добавлении брокера не
    изменится. Хотя бы одна недоступная зависимость — **503**:
    оркестратор обязан снять такую реплику с балансировки, а 200 с
    полем «плохо» внутри тела он не читает.

    Как именно проверяется каждая зависимость, знают пробы в
    ``app.api.deps`` — единственном месте вне ``app.repositories``,
    которому позволено знать реализацию. Liveness-проба, наоборот, не
    обращается ни к чему: недоступная БД не повод убивать процесс.
    """
    checks = {
        "database": _OK if await probe_database(request.app) else _UNAVAILABLE,
        "redis": _OK if await probe_denylist(request.app) else _UNAVAILABLE,
    }
    ready = all(check == _OK for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else _UNAVAILABLE, "checks": checks}
