"""Общие фикстуры тестов сервиса users.

Первый блок — инфраструктура контрактных тестов репозитория пользователей
(фикстура ``user_db``): чистый слой хранилища без HTTP. Второй блок —
окружение, приложение, HTTP-клиент и хелперы для тестов API.
"""

import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import NullPool

from app.auth.backend import build_jwt_strategy
from app.auth.user_protocol import AppUserProtocol
from app.business.domain.entities import InstitutionContext, User
from app.core.config import get_settings
from app.main import create_app
from app.repositories.database import Base, create_engine, create_session_factory
from app.repositories.denylist import InMemoryTokenDenylist
from app.repositories.in_memory import InMemoryUserDatabase
from app.repositories.memory_store import InMemoryUserStore
from app.repositories.protocols import UserRepository
from app.repositories.sql_alchemy import SqlAlchemyUserRepository


def generate_keypair() -> tuple[str, str]:
    """Сгенерировать пару ключей подписи в PEM.

    Ключи генерируются, а не хранятся в репозитории: приватный ключ в
    файлах проекта — даже тестовый — рано или поздно уезжает в реальную
    конфигурацию по копипасте.
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


@pytest.fixture(scope="session")
def keypair() -> tuple[str, str]:
    """Пара ключей, которой подписывает и проверяет тестовый сервис."""
    return JWT_PRIVATE_KEY, JWT_PUBLIC_KEY


@pytest.fixture(scope="session")
def foreign_keypair() -> tuple[str, str]:
    """Чужая пара ключей — для токенов, которые сервис принимать не должен."""
    return generate_keypair()


DEFAULT_EMAIL = "student@example.com"
DEFAULT_PASSWORD = "correct-horse-battery-staple"
BOOTSTRAP_EMAIL = "owner@example.com"
BOOTSTRAP_PASSWORD = "correct-horse-battery-staple"


# Переменная с DSN тестовой базы. Отдельная от ``USERS_DATABASE_URL``
# намеренно: фикстуры ниже пересоздают схему целиком, и указать сюда
# рабочую базу по невнимательности стоило бы всех её данных.
TEST_DATABASE_URL_ENV = "USERS_TEST_DATABASE_URL"

# Контрактные тесты, которые на SQLAlchemy проверяют не то, ради чего
# писались. См. ``skip_if_incompatible_with_sqlalchemy``.
SQLALCHEMY_INCOMPATIBLE_TESTS = frozenset({"test_read_returns_detached_copy"})

# Вариант параметризации «реальная PostgreSQL». Маркер ``db`` стоит на
# самом параметре, а не на тестовом файле: обычный прогон отсекает его
# через ``addopts``, а вариант ``in_memory`` тех же тестов остаётся.
POSTGRES_PARAM = pytest.param("postgres", marks=pytest.mark.db)


def require_test_database_url() -> str:
    """Вернуть DSN тестовой базы или пропустить тест.

    Именно ``skip``, а не падение: прогон без поднятого docker обязан
    оставаться зелёным, иначе маркер ``db`` пришлось бы дублировать
    ещё и в голове разработчика.
    """
    url = (os.environ.get(TEST_DATABASE_URL_ENV) or "").strip()
    if not url:
        pytest.skip(
            f"{TEST_DATABASE_URL_ENV} не задан: тесты против реальной PostgreSQL "
            "требуют поднятого docker-стека"
        )
    return url


def skip_if_incompatible_with_sqlalchemy(request: pytest.FixtureRequest) -> None:
    """Не запускать на PostgreSQL тесты, чей контракт держит только память.

    Пока это один тест — ``test_read_returns_detached_copy`` (он есть в
    обоих контрактных файлах). Причина расхождения, а не дефекта:
    адаптер SQLAlchemy работает поверх одной сессии, повторный ``get``
    отдаёт тот же объект из identity map, а ``select`` перед этим делает
    autoflush и записывает чужую мутацию в БД. Ослаблять ассерт нельзя:
    тест заводился как защита in-memory адаптера от возврата ссылок на
    хранимые записи, и на in-memory он продолжает работать целиком.
    """
    if request.node.originalname in SQLALCHEMY_INCOMPATIBLE_TESTS:
        pytest.skip(
            "Семантика identity map и autoflush в SQLAlchemy отличается от "
            "in-memory: тест защищает только in-memory адаптер"
        )


@asynccontextmanager
async def postgres_schema(database_url: str) -> AsyncIterator[AsyncEngine]:
    """Пересоздать схему в тестовой базе и отдать движок поверх неё.

    Схема снимается с моделей (``Base.metadata``), а не прогоном
    alembic: миграции применяются к рабочей базе шагом ``migrate`` в
    compose, а ``alembic upgrade`` в тестах пришлось бы запускать через
    ``asyncio.run`` внутри уже работающего цикла. Соответствие миграции
    и моделей проверяется отдельно — ручной проверкой схемы.

    ``drop_all`` вызывается и до, и после: до — чтобы упавший прошлый
    прогон не оставил чужих строк, после — чтобы тестовая база не
    копила мусор. Движок функциональный и с ``NullPool``: при
    ``asyncio_default_fixture_loop_scope = "function"`` пул, переживший
    цикл фикстуры, даёт плавающее «Future attached to a different loop».
    """
    engine = create_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        yield engine
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
    finally:
        await engine.dispose()


@pytest.fixture(params=["in_memory", POSTGRES_PARAM])
async def user_db(request: pytest.FixtureRequest) -> AsyncIterator[UserRepository]:
    """Реализация репозитория под контрактный прогон.

    Оба варианта отдают один и тот же псевдоним ``UserRepository``,
    поэтому контрактный файл не знает, с чем работает. Фикстура
    функциональная: каждый тест получает пустое хранилище — в памяти
    новый словарь, в PostgreSQL заново созданную схему, — поэтому
    порядок тестов на результат не влияет.
    """
    if request.param == "in_memory":
        yield InMemoryUserDatabase(InMemoryUserStore())
        return

    skip_if_incompatible_with_sqlalchemy(request)
    async with postgres_schema(require_test_database_url()) as engine:
        async with create_session_factory(engine)() as session:
            yield SqlAlchemyUserRepository(session)


@pytest.fixture(autouse=True)
def service_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Рабочее окружение сервиса на время одного теста.

    Гарантирует: каждый тест видит валидные настройки и не наследует
    закэшированный ``Settings`` от соседа — кэш сбрасывается и до, и
    после теста. Сид bootstrap-админа отключён, чтобы в хранилище не
    появлялось незапрошенных учёток.
    """
    get_settings.cache_clear()
    monkeypatch.setenv("USERS_JWT_PRIVATE_KEY", JWT_PRIVATE_KEY)
    monkeypatch.setenv("USERS_JWT_PUBLIC_KEY", JWT_PUBLIC_KEY)
    monkeypatch.setenv("USERS_ENVIRONMENT", "test")
    monkeypatch.setenv("USERS_LOG_LEVEL", "WARNING")
    # Обычные тесты идут на хранилище в памяти и не требуют docker.
    # Режим выставляется здесь явно, а не угадывается в рантайме;
    # DB-тесты переопределяют его собственной фикстурой.
    monkeypatch.setenv("USERS_STORAGE_BACKEND", "memory")
    monkeypatch.delenv("USERS_DATABASE_URL", raising=False)
    monkeypatch.delenv("USERS_REDIS_URL", raising=False)
    monkeypatch.delenv("USERS_BOOTSTRAP_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("USERS_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    # Пусто по умолчанию: в USERS_ENVIRONMENT=test это законно (см.
    # ``_check_internal_secret``), а любой вызов внутреннего API без
    # заданного секрета получает SERVICE_AUTH_FAILED — ровно то, что
    # нужно тестам, которые секрет не запрашивали намеренно.
    monkeypatch.delenv("USERS_INTERNAL_GAMIFICATION_SECRET", raising=False)
    monkeypatch.delenv("USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS", raising=False)
    yield
    get_settings.cache_clear()


@pytest.fixture
def app(service_env: None) -> FastAPI:
    """Свежее приложение на каждый тест.

    Хранилище живёт в ``app.state``, поэтому новое приложение — это и
    есть чистое состояние: чистить таблицы между тестами не требуется.
    """
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP-клиент поверх ASGI с явно запущенным lifespan.

    ``ASGITransport`` сам lifespan не выполняет, а без него не будет
    ``app.state.user_storage`` и любой запрос упадёт с ошибкой.
    """
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


@pytest.fixture
def bootstrap_admin(
    service_env: None, monkeypatch: pytest.MonkeyPatch
) -> tuple[str, str]:
    """Включить сид владельца инсталляции для одного теста.

    Запрашивается **до** ``client`` в списке аргументов теста: сид
    выполняется в ``lifespan``, то есть в момент создания приложения, и
    переменные должны быть выставлены раньше.
    """
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_EMAIL", BOOTSTRAP_EMAIL)
    monkeypatch.setenv("USERS_BOOTSTRAP_ADMIN_PASSWORD", BOOTSTRAP_PASSWORD)
    get_settings.cache_clear()
    return BOOTSTRAP_EMAIL, BOOTSTRAP_PASSWORD


@pytest.fixture
def user_storage(app: FastAPI, client: AsyncClient) -> InMemoryUserStore:
    """Прямой доступ к хранилищу приложения в обход API.

    Нужен там, где состояние по контракту API не меняется: деактивация
    учётки, назначение роли, выдача ``is_superuser``. Допустимо только
    в тестах. Зависимость от ``client`` обязательна: хранилище создаёт
    lifespan.
    """
    return app.state.user_storage


@pytest.fixture
def find_user(user_storage: InMemoryUserStore) -> Callable[[str], User]:
    """Хелпер чтения и правки хранимой записи пользователя по email."""

    def _find_user(email: str) -> User:
        return user_storage.users[user_storage.email_index[email.lower()]]

    return _find_user


@pytest.fixture
def context_token(
    app: FastAPI,
) -> Callable[..., Awaitable[str]]:
    """Выпустить токен в контексте учреждения — тем же вызовом, что и
    внутренний эндпоинт ``POST /internal/tokens/institution-context``.

    Стратегия собирается вне запроса, поэтому denylist ей передаётся
    явно; на выпуск он не влияет.
    """

    async def _context_token(
        user: AppUserProtocol, context: InstitutionContext | None = None
    ) -> str:
        strategy = build_jwt_strategy(InMemoryTokenDenylist())
        return await strategy.write_token(user, context)

    return _context_token


@pytest.fixture
def register(client: AsyncClient) -> Callable[..., Awaitable[Response]]:
    """Хелпер регистрации: ``POST /users/auth/register`` с переданным телом."""

    async def _register(
        email: str = DEFAULT_EMAIL,
        password: str = DEFAULT_PASSWORD,
        **extra: object,
    ) -> Response:
        payload: dict[str, object] = {"email": email, "password": password, **extra}
        return await client.post("/users/auth/register", json=payload)

    return _register


@pytest.fixture
def login(client: AsyncClient) -> Callable[..., Awaitable[Response]]:
    """Хелпер входа: ``POST /users/auth/jwt/login`` формой, как требует роутер."""

    async def _login(
        email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD
    ) -> Response:
        return await client.post(
            "/users/auth/jwt/login", data={"username": email, "password": password}
        )

    return _login


@pytest.fixture
def get_token(
    register: Callable[..., Awaitable[Response]],
    login: Callable[..., Awaitable[Response]],
) -> Callable[..., Awaitable[str]]:
    """Зарегистрировать пользователя и вернуть его токен доступа.

    Ответ регистрации намеренно не проверяется: хелпер вызывается и для
    уже заведённого email, а его успешность подтверждает следующий за
    ней вход.
    """

    async def _get_token(
        email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD
    ) -> str:
        await register(email, password)
        response = await login(email, password)
        assert response.status_code == 200, response.text
        return response.json()["access_token"]

    return _get_token


@pytest.fixture
def auth_headers(
    get_token: Callable[..., Awaitable[str]],
) -> Callable[..., Awaitable[dict[str, str]]]:
    """Заголовок ``Authorization`` для зарегистрированного пользователя."""

    async def _auth_headers(
        email: str = DEFAULT_EMAIL, password: str = DEFAULT_PASSWORD
    ) -> dict[str, str]:
        token = await get_token(email, password)
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers
