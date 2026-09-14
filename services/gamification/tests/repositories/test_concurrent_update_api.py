"""API-ответ на ``ConcurrentUpdateError`` (решение владельца от 2026-09-14).

Маршрут добавляется временно на тестовое приложение — сама доменная
ошибка возникает только из PostgreSQL (SQLSTATE ``40P01``/``40001``),
воспроизводить реальную гонку блокировок здесь не нужно: проверяется
только перевод исключения в HTTP-ответ, зарегистрированный в
``app/core/exceptions.py``.
"""

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.business.domain.errors import ConcurrentUpdateError


async def test_concurrent_update_error_maps_to_409(app: FastAPI) -> None:
    @app.get("/__test/concurrent-update")
    async def _raise_concurrent_update() -> None:
        raise ConcurrentUpdateError

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/__test/concurrent-update")

    assert response.status_code == 409
    assert response.json() == {"detail": "CONCURRENT_UPDATE"}
