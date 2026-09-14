"""Корневой роутер HTTP API сервиса gamification.

Здесь собрана вся карта адресов сервиса — как в
``services/users/app/api/main_router.py``: модули роутеров объявляют
голый ``APIRouter()`` и пути относительно префикса, а ``prefix`` и
``tags`` задаются здесь, при подключении. Исключение — health: он
живёт в корне сервиса и префикса не получает.

* ``/institutions`` — внешнее API, публикуется наружу через шлюз;
  роутеры учреждений и приглашений делят этот префикс;
* ``/internal/...`` — вызовы от других сервисов; в этом этапе пусто —
  gamification пока никто не зовёт;
* ``/health`` — пробы оркестратора, вне аутентификации.
"""

from fastapi import APIRouter

from app.api.external.currency import router as currency_router
from app.api.external.groups import router as groups_router
from app.api.external.health import router as health_router
from app.api.external.institutions import router as institutions_router
from app.api.external.invitations import router as invitations_router
from app.api.external.market import router as market_router
from app.api.external.students import router as students_router
from app.api.external.teachers import router as teachers_router
from app.api.internal.internal_router import router as internal_router

api_router = APIRouter()

api_router.include_router(health_router, tags=["health"])
api_router.include_router(internal_router, prefix="/internal", include_in_schema=False)
api_router.include_router(
    institutions_router, prefix="/institutions", tags=["institutions"]
)
api_router.include_router(
    invitations_router, prefix="/institutions", tags=["invitations"]
)
api_router.include_router(teachers_router, prefix="/institutions", tags=["teachers"])
api_router.include_router(students_router, prefix="/institutions", tags=["students"])
api_router.include_router(groups_router, prefix="/institutions", tags=["groups"])
api_router.include_router(currency_router, prefix="/institutions", tags=["currency"])
api_router.include_router(market_router, prefix="/institutions", tags=["market"])
