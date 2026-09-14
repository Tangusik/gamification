"""Общие фикстуры тестов сервиса gamification."""

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app

AUDIENCE = ["fastapi-users:auth"]


def generate_keypair() -> tuple[str, str]:
    """Сгенерировать пару ключей подписи в PEM.

    Ключи генерируются, а не хранятся в репозитории: приватный ключ в
    файлах проекта рано или поздно уезжает в реальную конфигурацию по
    копипасте. Приватный ключ здесь нужен только тестам — сам сервис
    его не хранит и не использует.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


# Одна пара на весь прогон: генерация RSA дороже самих тестов.
JWT_PRIVATE_KEY, JWT_PUBLIC_KEY = generate_keypair()
SERVICE_SECRET = "test-service-secret-" + "x" * 20


@pytest.fixture(scope="session")
def keypair() -> tuple[str, str]:
    """Пара ключей, которой тесты подписывают токены для этого сервиса."""
    return JWT_PRIVATE_KEY, JWT_PUBLIC_KEY


@pytest.fixture(scope="session")
def foreign_keypair() -> tuple[str, str]:
    """Чужая пара ключей — для токенов, которые сервис принимать не должен."""
    return generate_keypair()


@pytest.fixture(autouse=True)
def service_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Рабочее окружение сервиса на время одного теста.

    Все настройки, влияющие на прогон, выставляются явно через
    ``monkeypatch.setenv``, а значит — через процессное окружение,
    которое у pydantic-settings приоритетнее файла ``.env`` (риск 14 из
    плана: скелет копирует ``env_file=".env"`` из users). ``DATABASE_URL``
    и ``REDIS_URL`` гасятся тем же способом — ``setenv("")``, а не
    ``delenv``: у ``delenv`` переменная просто отсутствует в окружении, и
    тогда pydantic-settings читает файл ``.env`` из текущего каталога,
    если разработчик его там заведёт (дефект users из
    ``.claude/knowledge/users-service/06-open-items.md``). Пустая строка
    в окружении — тоже полноценное значение переменной, приоритетнее
    файла, а ``Settings`` уже трактует пустой ``database_url``/
    ``redis_url`` как «не задано» (см. ``_check_storage_backend`` и
    ``_check_denylist_backend`` в ``app/core/config.py``). Тест
    ``test_env_file_in_cwd_does_not_leak_storage_settings`` в
    ``tests/test_health.py`` доказывает, что боевой ``.env`` в cwd не
    подсовывает свои DSN.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("GAMIFICATION_JWT_PUBLIC_KEY", JWT_PUBLIC_KEY)
    monkeypatch.setenv("GAMIFICATION_JWT_ALGORITHM", "RS256")
    monkeypatch.setenv("GAMIFICATION_ENVIRONMENT", "test")
    monkeypatch.setenv("GAMIFICATION_LOG_LEVEL", "WARNING")
    monkeypatch.setenv("GAMIFICATION_STORAGE_BACKEND", "memory")
    monkeypatch.setenv("GAMIFICATION_USERS_SERVICE_SECRET", SERVICE_SECRET)
    monkeypatch.setenv("GAMIFICATION_DATABASE_URL", "")
    monkeypatch.setenv("GAMIFICATION_REDIS_URL", "")
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(service_env: None) -> FastAPI:
    """Свежее приложение на каждый тест."""
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент поверх ASGI с явно запущенным lifespan."""
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


def make_token(
    *,
    subject: uuid.UUID | None = None,
    institution_id: uuid.UUID | None = None,
    role: str | None = None,
    private_key: str = JWT_PRIVATE_KEY,
    audience: list[str] | None = None,
    algorithm: str = "RS256",
    expires_delta: timedelta | None = timedelta(minutes=15),
    token_id: str | None = "11111111-2222-4333-8444-555555555555",
    include_exp: bool = True,
) -> str:
    """Подписать токен для тестов проверки аутентификации и API."""
    payload: dict[str, object] = {
        "sub": str(subject or uuid.uuid4()),
        "aud": AUDIENCE if audience is None else audience,
        "jti": token_id,
        "role": role,
        "institution_id": str(institution_id) if institution_id else None,
    }
    if include_exp and expires_delta is not None:
        payload["exp"] = datetime.now(UTC) + expires_delta
    return jwt.encode(payload, private_key, algorithm=algorithm)


@pytest.fixture
def token_factory():
    """Хелпер-фикстура поверх ``make_token`` для тестов, где удобнее DI."""
    return make_token
