# Сервис users

Микросервис пользователей платформы геймификации обучения: регистрация,
аутентификация, профиль и подпись токенов. Стек: Python 3.13, FastAPI,
fastapi-users, SQLAlchemy (async, asyncpg), PostgreSQL, Redis, alembic,
pydantic-settings.

Учреждения, членства и роли — ответственность сервиса `gamification`: он
источник истины о том, кто состоит в каком учреждении и с какой ролью. У
users остаётся личность, аутентификация, подпись токенов (приватный ключ)
и denylist. Единственная точка их встречи — внутренний эндпоинт
`POST /internal/tokens/institution-context`: gamification проверяет
членство сама и просит users перевыпустить токен пользователя уже с
контекстом учреждения (см. «Внутреннее API» ниже).

## Запуск через docker

Самый короткий путь: весь стек разработки поднимается из корня репозитория одной
командой.

```bash
cp deploy/.env.example .env
# Заполнить USERS_JWT_PRIVATE_KEY и USERS_JWT_PUBLIC_KEY — см. «Ключи подписи».

docker compose -f docker-compose.dev.yml up -d --build
```

Поднимаются пять сервисов: `postgres`, `redis`, одноразовый `migrate`
(`alembic upgrade head`, выполняется до старта приложения), `users` и `pgadmin`.
Порты dev-стека публикуются **только на `127.0.0.1`** — окружение с dev-паролями
в локальную сеть не выставляется:

| Адрес | Что это |
| --- | --- |
| <http://127.0.0.1:8000> | Сервис users; документация — `/docs` |
| <http://127.0.0.1:5050> | pgAdmin; логин и пароль — `PGADMIN_*` из `.env` |
| `127.0.0.1:5432` | PostgreSQL; сюда же ходят `pytest -m db` |

Redis наружу не публикуется вовсе: с хоста он не нужен никому.

Деплойный `docker-compose.yml` — отдельный файл, и запускать его следует **только с
явным `--env-file`**:

```bash
docker compose --env-file deploy/.env.production -f docker-compose.yml up -d
```

Без `--env-file` compose подхватит корневой `.env`, то есть файл окружения
**разработки**: dev-пароль базы, пару ключей разработчика и
`USERS_ENVIRONMENT=local`, который перебьёт дефолт `production`. Ошибка тихая — ни
compose, ни сервис на неё не возражают.

## Локальный запуск без docker

```bash
cd services/users
python -m venv .venv

# Общая библиотека проверки токенов ставится ПЕРВОЙ: сервис объявляет её
# в зависимостях по имени, а в PyPI её нет.
.venv/Scripts/python.exe -m pip install -e ../../libs/gamification-auth
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # Linux/macOS

cp .env.example .env
# Заполнить USERS_JWT_PRIVATE_KEY и USERS_JWT_PUBLIC_KEY — см. ниже,
# и USERS_DATABASE_URL: без него сервис не стартует.

.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --port 8000 --workers 1
```

Базу и Redis при таком запуске проще всего взять из dev-стека: он публикует
PostgreSQL на `127.0.0.1:5432`, тогда
`USERS_DATABASE_URL=postgresql+asyncpg://users:<пароль>@127.0.0.1:5432/users`.
Схему создаёт alembic — см. «Миграции схемы».

### Ключи подписи

Подпись асимметричная (RS256): приватный ключ есть только у этого сервиса, остальные
проверяют токены публичным и подделать их не могут.

```bash
.venv/Scripts/python.exe -c "
from cryptography.hazmat.primitives import serialization as s
from cryptography.hazmat.primitives.asymmetric import rsa
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
print(key.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption()).decode())
print(key.public_key().public_bytes(s.Encoding.PEM, s.PublicFormat.SubjectPublicKeyInfo).decode())
"
```

Первый блок — в `USERS_JWT_PRIVATE_KEY`, второй — в `USERS_JWT_PUBLIC_KEY`, целиком,
вместе со строками `BEGIN`/`END`. Сервис отказывается стартовать, если ключ не в
формате PEM или если в переменную публичного ключа попал приватный: значение этой
переменной раздаётся другим сервисам.

Приложение собирается фабрикой `create_app`, поэтому запуск обязательно
с флагом `--factory`: модульного объекта `app` нет намеренно, чтобы импорт
модуля не требовал переменных окружения.

Документация OpenAPI: <http://localhost:8000/docs>, схема — `/openapi.json`.

## Карта адресов

Внешнее API целиком лежит под префиксом `/users`, включая аутентификацию.
Снаружи сервис публикуется одним префиксом шлюза: `/api/v1/users/` →
`/users/` сервиса. Всё, что лежит вне `/users`, наружу не попадает.

| Метод | Путь | Публичный адрес | Назначение |
| --- | --- | --- | --- |
| `POST` | `/users/auth/register` | `/api/v1/users/auth/register` | Регистрация |
| `POST` | `/users/auth/jwt/login` | `/api/v1/users/auth/jwt/login` | Вход, токен **без** контекста учреждения |
| `POST` | `/users/auth/jwt/logout` | `/api/v1/users/auth/jwt/logout` | Выход; гасит токен по `jti` |
| `GET`, `PATCH` | `/users/me` | `/api/v1/users/me` | Свой профиль |
| `GET`, `PATCH`, `DELETE` | `/users/{id}` | `/api/v1/users/{id}` | Библиотечный роутер, только под `is_superuser` |
| — | `/internal/...` | не публикуется | Вызовы от других сервисов (см. «Внутреннее API») |
| `GET` | `/health` | не публикуется | Liveness, без аутентификации |
| `GET` | `/health/ready` | не публикуется | Readiness: `{"status": "ready", "checks": {"database": ..., "redis": ...}}`, 503 при любой недоступной зависимости |

`/health` и `/internal` лежат вне `/users`, поэтому выставить их наружу через
шлюз нельзя даже по ошибке — пробы оркестратора ходят напрямую по порту сервиса.

**Ломающее изменение относительно предыдущего этапа:** `POST /users/auth/institution`
и `GET /users/me/institutions` удалены — учреждения и членства переехали в
gamification. Их место заняли `POST /api/v1/institutions/{id}/token` и
`GET /api/v1/institutions` (там же), пользующиеся внутренним эндпоинтом ниже.

## Внутреннее API

`POST /internal/tokens/institution-context` — единственный внутренний эндпоинт,
вызывает его только gamification при переключении учреждения (клиент → gamification →
этот эндпоинт → клиент). Лежит вне `/users`, `include_in_schema=False`, в
`/openapi.json` не попадает.

Служебная аутентификация — заголовок `X-Service-Secret`, сравнение с
`USERS_INTERNAL_GAMIFICATION_SECRET` (и, на время ротации, с
`USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS`) за постоянное время. Тело:

```json
{"subject_token": "<токен, который пользователь предъявил gamification>",
 "institution_id": "<uuid>",
 "role": "student"}
```

users сам проверяет `subject_token` (подпись, `exp`, `aud`, отзыв по denylist),
существование и активность пользователя и считает срок нового токена как
`min(exp предъявленного, now + USERS_JWT_LIFETIME_SECONDS)` — сессию через этот путь
продлить нельзя. На веру принимается только пара «`institution_id` + `role`»: это
ответственность gamification, у users больше нет хранилища членств, чтобы её
перепроверить. Ответ — `{"access_token": "...", "token_type": "bearer"}` с заголовком
`Cache-Control: no-store`. Каждый выпуск пишется в аудит-лог (вызывающий, `sub`,
`institution_id`, `role`, новый `jti`); сам токен и секрет в лог не попадают никогда.

Коды ошибок — отдельное пространство, в ответ пользователю не транслируются как есть:
`SERVICE_AUTH_FAILED` (401, неверный или отсутствующий секрет) и
`SUBJECT_TOKEN_REJECTED` (403, `subject_token` невалиден, истёк, отозван, пользователя
нет или он неактивен, либо остаток жизни токена истёк).

## Переменные окружения

Все переменные имеют префикс `USERS_`, читаются из окружения или файла `.env`.

| Переменная | Обязательна | По умолчанию | Назначение |
| --- | --- | --- | --- |
| `USERS_APP_NAME` | нет | `users` | Имя сервиса в логах и в заголовке OpenAPI |
| `USERS_ENVIRONMENT` | нет | `local` | Имя окружения; значения `local` и `test` разрешают реализации в памяти |
| `USERS_LOG_LEVEL` | нет | `INFO` | Уровень логирования |
| `USERS_ROOT_PATH` | нет | — | Публичный префикс шлюза (`/api/v1`); маршруты не префиксует, влияет только на OpenAPI и `/docs` |
| `USERS_JWT_PRIVATE_KEY` | **да** | — | Приватный ключ подписи в PEM; не покидает сервис |
| `USERS_JWT_PUBLIC_KEY` | **да** | — | Публичный ключ в PEM; раздаётся другим сервисам для проверки |
| `USERS_JWT_ALGORITHM` | нет | `RS256` | Алгоритм подписи JWT |
| `USERS_JWT_LIFETIME_SECONDS` | нет | `900` | Время жизни токена доступа, секунды; строго больше нуля |
| `USERS_BOOTSTRAP_ADMIN_EMAIL` | нет | — | Email стартового администратора |
| `USERS_BOOTSTRAP_ADMIN_PASSWORD` | нет | — | Пароль стартового администратора, минимум 8 символов |
| `USERS_STORAGE_BACKEND` | нет | `postgres` | Реализация хранилища: `postgres` или `memory` |
| `USERS_DATABASE_URL` | **при `postgres`** | — | DSN async-движка: `postgresql+asyncpg://user:password@host:port/dbname` |
| `USERS_REDIS_URL` | **вне local/test** | — | Адрес denylist отозванных токенов: `redis://host:port/db` |
| `USERS_INTERNAL_GAMIFICATION_SECRET` | **вне local/test** | пусто | Служебный секрет вызывающего (gamification) на внутренний выпуск токена; минимум 32 символа |
| `USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS` | нет | — | Второй секрет на время ротации; если задан — тоже минимум 32 символа |

Четыре правила связывают эти переменные между собой; каждое нарушение роняет создание
`Settings`, то есть старт сервиса — тихо работать с неверным хранилищем хуже, чем не
стартовать:

- `USERS_STORAGE_BACKEND=postgres` (умолчание) требует непустого `USERS_DATABASE_URL`.
  Умолчание именно `postgres`, чтобы забытая переменная не дала молча хранилище в
  памяти, теряющее данные при рестарте.
- `USERS_STORAGE_BACKEND=memory` допустим, только если `USERS_ENVIRONMENT` — `local`
  или `test`. В остальных окружениях это молчаливая потеря данных.
- Пустой `USERS_REDIS_URL` означает denylist в памяти процесса и допустим по тому же
  правилу: только при `USERS_ENVIRONMENT` из `local`/`test`. В остальных окружениях
  такой отзыв не виден ни второй реплике, ни самому процессу после рестарта.
- `USERS_INTERNAL_GAMIFICATION_SECRET` короче 32 символов (включая пустое значение) не
  проходит вне `local`/`test`. В `local`/`test` пустое значение допустимо для старта,
  но тогда любой вызов внутреннего эндпоинта отвергается `SERVICE_AUTH_FAILED`: пустая
  строка сравнением никогда не совпадает. То же правило действует на
  `USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS`, если он вообще задан.

Приватный ключ, пароль администратора, DSN базы, URL Redis и служебный секрет содержат
секреты, поэтому жалобы валидации на них — собственное `InsecureSettingError`, а не
`ValidationError`: последний всегда печатает `input_value`, то есть само значение,
независимо от `SecretStr`. Публичный ключ обёрнут в `SecretStr` по той же причине — в
его переменную по ошибке попадает приватный.

## Миграции схемы

Команды запускаются из `services/users`; `alembic.ini` намеренно не содержит
`sqlalchemy.url` — адрес базы `alembic/env.py` берёт из `Settings`.

```bash
.venv/Scripts/python.exe -m alembic upgrade head          # применить всё
.venv/Scripts/python.exe -m alembic current               # текущая ревизия
.venv/Scripts/python.exe -m alembic downgrade -1          # откатить одну
.venv/Scripts/python.exe -m alembic revision --autogenerate -m "..."
```

**Одного `USERS_DATABASE_URL` для этого мало.** DSN читается из `Settings`, а те
требуют ещё и пару ключей подписи — без `USERS_JWT_PRIVATE_KEY` и
`USERS_JWT_PUBLIC_KEY` команда падает на валидации настроек, не дойдя до базы. Шаг
миграций поэтому запускается с тем же набором переменных, что и сам сервис; в compose
это общий якорь `x-users-env`, локально — тот же `.env`.

Ревизии нумеруются вручную (`0001_`, `0002_`, ...), чтобы порядок читался из листинга
каталога. Применённые миграции не правятся.

В dev-стеке миграции уже прогнаны одноразовым сервисом `migrate`: он выполняется до
старта `users`, и приложение поднимается только после его успешного завершения.

## Отзыв токенов

Выход (`POST /users/auth/jwt/logout`) гасит токен по claim `jti`, а не по его телу:
иначе тот же токен в другом представлении остался бы живым. Запись в denylist живёт
ровно до `exp` токена (TTL = `exp - now`), поэтому хранилище самоочищается и не растёт.

При недоступном Redis проверка отзыва работает **fail-open**: запрос не отклоняется,
отзыв временно не действует, а факт пишется в лог уровнем `error`. Это решение
владельца проекта, а не дефект: верхняя граница ущерба — время жизни access-токена
(15 минут по умолчанию), и на ней же стоит правило про остаток срока у токена с
контекстом учреждения. Молчаливый fail-open был бы неотличим от работающего отзыва,
поэтому запись в лог обязательна.

## Разработка

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m pytest

# Общая библиотека проверки токенов: своего окружения у неё пока нет
.venv/Scripts/python.exe -m pytest ../../libs/gamification-auth
.venv/Scripts/python.exe -m ruff check ../../libs/gamification-auth
```

Обычный `pytest` docker не требует: тесты против реальной базы помечены маркером `db`
и отсекаются `addopts = "-m 'not db'"` из `pyproject.toml`. Запускаются они явно и
только вместе с DSN тестовой базы:

```bash
USERS_TEST_DATABASE_URL="postgresql+asyncpg://users:<пароль>@127.0.0.1:5432/users_test" \
  .venv/Scripts/python.exe -m pytest -m db
```

Базу `users_test` создаёт скрипт `deploy/postgres/init/01-create-test-db.sql` при
первичной инициализации кластера, то есть на пустом томе. Отдельная база нужна потому,
что DB-тесты чистят таблицы между прогонами и не должны трогать рабочую базу
разработчика. Без `USERS_TEST_DATABASE_URL` пакет `tests/db` не падает, а
пропускается с указанием причины.

## Ограничения текущего этапа

Хранилище в памяти больше не ограничение сервиса: данные лежат в PostgreSQL, операции
идут в транзакции сессии запроса, уникальность email закрыта индексом на `lower(email)`
в базе, отзыв токенов — в Redis. Несколько реплик допустимы.

Реализации в памяти остались, но в двух ролях:

- **тестовый дублёр** — контрактные тесты репозиториев и тесты выхода из системы не
  должны требовать поднятого docker;
- **режим `USERS_STORAGE_BACKEND=memory`**, разрешённый только при `USERS_ENVIRONMENT`
  из `{local, test}`. В любом другом окружении сервис с ним не стартует. В этом режиме
  состояние принадлежит процессу: строго один воркер и одна реплика, данные теряются
  при рестарте.

Что в этап по-прежнему не входит:

- учреждения, членства, роли, приглашения — они в сервисе `gamification`;
- refresh-токены — длинная сессия пока не поддержана;
- ротация служебного секрета внутреннего API через что-то кроме второй переменной
  (`USERS_INTERNAL_GAMIFICATION_SECRET_PREVIOUS`) — путь перехода на mTLS (C3)
  записан в `.claude/knowledge`, но не реализован;
- RabbitMQ, k8s, OAuth, верификация email и сброс пароля (`get_verify_router` и
  `get_reset_password_router` намеренно не подключены).
