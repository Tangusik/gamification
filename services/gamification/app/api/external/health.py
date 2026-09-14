"""Health-эндпоинты сервиса: liveness и readiness.

Роутер голый: ``prefix`` и ``tags`` задаются в ``app/api/main_router.py``.
"""

from fastapi import APIRouter, Request, Response, status

from app.api.deps import probe_database, probe_denylist

router = APIRouter()

_OK = "ok"
_UNAVAILABLE = "unavailable"


@router.get("/health")
async def liveness() -> dict[str, str]:
    """Liveness-проба: отвечает всегда, не обращается к зависимостям."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(request: Request, response: Response) -> dict[str, object]:
    """Readiness-проба: агрегирует состояние внешних зависимостей.

    Хотя бы одна недоступная зависимость — 503. Denylist users
    проверяется fail-open (K1): его недоступность видна здесь, но не
    отвергает запросы. Users как таковой не проверяется вовсе (раздел
    4.6): падение users не должно снимать с балансировки реплики,
    которым выпуск токена не нужен.
    """
    checks = {
        "database": _OK if await probe_database(request.app) else _UNAVAILABLE,
        "users_denylist": _OK if await probe_denylist(request.app) else _UNAVAILABLE,
    }
    ready = all(check == _OK for check in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if ready else _UNAVAILABLE, "checks": checks}
