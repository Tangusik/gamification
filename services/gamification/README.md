# Сервис gamification

Микросервис учреждений, членств и переключения учреждения. Стек: Python 3.13,
FastAPI, SQLAlchemy (async, asyncpg), PostgreSQL, alembic, Redis (только чтение
denylist users), pydantic-settings, httpx (вызов users). Эталон структуры —
`services/users`; отличия — в `.claude/plans/03-gamification-service.md`, раздел 2.

Зона ответственности этого этапа — учреждения, членства, переключение контекста
(раздел 4 плана) и приглашения (раздел 5 плана). Валюта, привилегии, XP,
лидерборды и показатели учеников в этап не входят.

## Локальный запуск без docker

```bash
cd services/gamification
python -m venv .venv

# Общая библиотека проверки токенов ставится ПЕРВОЙ.
.venv/Scripts/python.exe -m pip install -e ../../libs/gamification-auth
.venv/Scripts/python.exe -m pip install -e ".[dev]"   # Windows
# source .venv/bin/activate && pip install -e ".[dev]"  # Linux/macOS

cp .env.example .env
# Заполнить GAMIFICATION_JWT_PUBLIC_KEY — то же значение, что
# USERS_JWT_PUBLIC_KEY у сервиса users (J1), и GAMIFICATION_DATABASE_URL,
# и GAMIFICATION_USERS_SERVICE_SECRET (см. services/users/.env.example
# и .claude/knowledge — статический секрет C1 сейчас, путь перехода C3/mTLS).

.venv/Scripts/python.exe -m uvicorn app.main:create_app --factory --port 8001 --workers 1
```

Приложение собирается фабрикой `create_app`, поэтому запуск обязательно с флагом
`--factory`. Документация OpenAPI: `/docs`, схема — `/openapi-gamification.json`
(адрес `/openapi.json` за шлюзом занят users, раздел 8 плана).

## Карта адресов

Внешнее API целиком лежит под `/institutions`. Снаружи сервис публикуется через
шлюз под `/api/v1` (второй location, отдельно от `/api/v1/users/`).

| Метод | Путь | Контекст токена | Назначение |
| --- | --- | --- | --- |
| `POST` | `/institutions` | не нужен | Завести учреждение; создатель — `institution_admin` (E1) |
| `GET` | `/institutions` | не нужен | Свои членства — как раньше `GET /users/me/institutions` |
| `POST` | `/institutions/{institution_id:uuid}/token` | не нужен — это и есть переключение | Выпустить токен в контексте учреждения (раздел 4) |
| `POST` | `/institutions/{institution_id:uuid}/invitations` | контекст = `{institution_id}` (G1) | Завести приглашение (F3: `institution_admin`, `teacher`) |
| `GET` | `/institutions/{institution_id:uuid}/invitations` | то же | Список приглашений: админ — все, преподаватель — свои |
| `DELETE` | `/institutions/{institution_id:uuid}/invitations/{invitation_id:uuid}` | то же | Отозвать приглашение; идемпотентно, `204` |
| `POST` | `/institutions/invitations/accept` | не нужен (F4) | Принять приглашение по токену |
| — | `/internal/...` | — | Пусто в этом этапе: gamification пока никто не зовёт |
| `GET` | `/health`, `/health/ready` | — | Пробы оркестратора; readiness — 503 без БД |

`POST .../token` не обращается в users, если членства нет, оно неактивно или
учреждения не существует, — во всех трёх случаях один и тот же `NOT_A_MEMBER`.

## Приглашения (раздел 5 плана)

Приглашение бессрочно (F1): срока жизни нет, колонки `expires_at` тоже нет,
отзыв — только вручную. Ограничение — только число применений `max_uses`
(F2: по умолчанию 1, диапазон 1..100 в теле запроса создания). Роль в этом
этапе всегда `student` — приглашения преподавателей и админов не входят в
объём, колонка `role` под них заложена.

Токен — `secrets.token_urlsafe(32)` (256 бит). **Хранится восстановимо** — в
колонке `token` открытым текстом (F5, решение владельца против рекомендации
«только хеш»): нужно для перепечатки QR без выпуска новой ссылки. Отсюда же
следствие — `GET .../invitations` возвращает `token` в каждом элементе.
Ссылку `<origin>/invite#<token>` собирает клиент; сервер отдаёт только сам
токен и не рисует QR. Фрагмент (`#`) не должен попасть ни в access-лог nginx,
ни в `Referer`, ни в логи сервиса — токен и тело принятия не логируются нигде.

Создают приглашения `institution_admin` и `teacher` (F3): ученик получает
`403 INSUFFICIENT_ROLE`. Отзывает автор или админ; преподаватель, пытающийся
отозвать чужое приглашение (он его не видит в списке), получает тот же
`404 INVITATION_INVALID`, что и на несуществующий идентификатор — иначе ответ
выдавал бы сам факт существования приглашения.

Принятие (`POST /institutions/invitations/accept`) не требует контекста
токена (F4: у приглашённого ещё может не быть выбранного учреждения) и
идемпотентно по построению одной транзакцией:

1. приглашение ищется по токену с блокировкой строки (`SELECT ... FOR
   UPDATE`); не найдено или отозвано — `404 INVITATION_INVALID`;
2. активный участник получает `200` с уже существующим членством, роль не
   меняется, счётчик не растёт (F7); приостановленный (`SUSPENDED`) получает
   `403 MEMBERSHIP_SUSPENDED` и не реактивируется;
3. исчерпанный лимит применений — `404 INVITATION_INVALID`;
4. вставка нового членства идёт в SAVEPOINT; конфликт уникальности
   переводится в тот же идемпотентный `200` — параллельное принятие тем же
   пользователем не может дать `500`;
5. счётчик применений увеличивается, один `commit`.

## Переключение учреждения (раздел 4 плана)

Клиент предъявляет свой access-токен `gamification`. Она проверяет членство и
роль по своей базе, затем вызывает закрытый внутренний эндпоинт users
(`POST /internal/tokens/institution-context`, служебный секрет в заголовке
`X-Service-Secret`) с телом `{"subject_token", "institution_id", "role"}` и
отдаёт клиенту токен, который вернул users. Один `httpx.AsyncClient` на
приложение, таймаут 2 секунды на весь запрос, ретраев нет.

Реакция на ответы users:

| Ответ users | Клиенту |
| --- | --- |
| `200` | `200` с токеном, `Cache-Control: no-store` |
| `401 SERVICE_AUTH_FAILED` | `503 TOKEN_ISSUER_UNAVAILABLE` (авария на стороне gamification, не про права клиента) |
| `403 SUBJECT_TOKEN_REJECTED` | `401 Unauthorized` |
| `422` (дефект контракта) | `500 TOKEN_ISSUER_CONTRACT_ERROR` |
| таймаут, сеть, `5xx` | `503 TOKEN_ISSUER_UNAVAILABLE` |

## Переменные окружения

Все переменные имеют префикс `GAMIFICATION_`, читаются из окружения или файла
`.env`. Полный список с описанием — в `.env.example`.

Четыре правила связывают их между собой, каждое нарушение роняет старт:

- `GAMIFICATION_STORAGE_BACKEND=postgres` (умолчание) требует непустого
  `GAMIFICATION_DATABASE_URL`.
- `GAMIFICATION_STORAGE_BACKEND=memory` допустим только при
  `GAMIFICATION_ENVIRONMENT` из `local`/`test`.
- Пустой `GAMIFICATION_REDIS_URL` допустим по тому же правилу: иначе denylist
  users не проверяется вовсе.
- `GAMIFICATION_USERS_SERVICE_SECRET` короче 32 символов вне `local`/`test`
  роняет старт.

## Изоляция арендаторов (H1)

Репозитории учреждения создаются уже привязанными к `institution_id`:
`uow.for_institution(institution_id).memberships` — метода без фильтра по
арендатору не существует. Межарендная операция («мои членства» по `user_id`)
вынесена в отдельный порт с явным именем — `uow.user_memberships`.

## Миграции схемы

Команды запускаются из `services/gamification`; `alembic.ini` не содержит
`sqlalchemy.url` — адрес базы `alembic/env.py` берёт из `Settings`.

```bash
.venv/Scripts/python.exe -m alembic upgrade head
```

Ревизия `0001` создаёт `institutions`, `invitations` и `memberships` (с
колонкой `invitation_id`) одним релизом — этапы 3 и 4 плана уходят в одну
ревизию, ещё не применённую ни на одном стенде.

## База данных в существующем томе

`deploy/postgres/init/02-create-gamification-db.sh` создаёт роль и базы
`gamification` / `gamification_test` (I1) и роль приложения
`gamification_app` (У1), но, как и `01-create-test-db.sql`, отрабатывает
только при первичной инициализации тома `postgres-data` (риск 7 плана). На
уже поднятых dev- и деплойных томах база `gamification` и роль
`gamification_app` сами не появятся — нужен разовый ручной шаг.

Порядок для dev-тома (`docker-compose.dev.yml`):

1. Добавить `GAMIFICATION_APP_DB_PASSWORD` в корневой `.env`
   (см. `deploy/.env.example`).
2. Пересоздать контейнер `postgres`, чтобы он получил новую переменную;
   данные в томе `postgres-data` при этом сохраняются:

   ```bash
   docker compose -f docker-compose.dev.yml up -d postgres
   ```
3. Выполнить скрипт внутри уже работающего контейнера postgres **без `-e`**:
   переменные `GAMIFICATION_DB_PASSWORD` и `GAMIFICATION_APP_DB_PASSWORD` уже
   есть в окружении контейнера — они приходят туда из compose, поэтому
   передавать пароль вручную через `-e` не нужно (иначе он остаётся в
   истории оболочки):

   ```bash
   docker exec gamification-dev-postgres-1 \
     sh /docker-entrypoint-initdb.d/02-create-gamification-db.sh
   ```

   Имя контейнера соответствует имени compose-проекта: `gamification-dev-*`
   для `docker-compose.dev.yml` (`name: gamification-dev`), `gamification-*`
   для деплойного `docker-compose.yml`. Скрипт идемпотентен: повторный ручной
   запуск не падает — существующие роль и базы пропускаются, пароль роли
   обновляется на текущее значение переменной.
4. Пересобрать и поднять `migrate-gamification` и `gamification`, чтобы они
   подхватили `gamification_app`:

   ```bash
   docker compose -f docker-compose.dev.yml up -d --build migrate-gamification gamification
   ```

Для деплойного тома (`docker-compose.yml`) каталог `deploy/postgres/init` не
монтируется целиком: смонтирован только сам файл
`02-create-gamification-db.sh` (см. `docker-compose.yml`), имя контейнера —
`gamification-postgres-1`. `docker-compose.yml` запускается **только с
явным `--env-file`** (заголовок файла) — без него compose молча подставит
корневой dev-`.env` и переустановит на боевом кластере пароли ролей
`gamification`/`gamification_app` на dev-значения (L2). Ниже — шаги 2–4 с
файлом `deploy/.env.production` как примером; вместо него подставить
реальный env-file деплоя:

2. Пересоздать контейнер `postgres`, чтобы он получил новую переменную:

   ```bash
   docker compose --env-file deploy/.env.production -f docker-compose.yml \
     up -d postgres
   ```
3. Выполнить скрипт внутри уже работающего контейнера postgres, без `-e`
   (переменные приходят из compose):

   ```bash
   docker exec gamification-postgres-1 \
     sh /docker-entrypoint-initdb.d/02-create-gamification-db.sh
   ```
4. Пересобрать и поднять `migrate-gamification` и `gamification` с тем же
   env-file:

   ```bash
   docker compose --env-file deploy/.env.production -f docker-compose.yml \
     up -d --build migrate-gamification gamification
   ```

`GRANT` на таблицы и политики RLS для `gamification_app` делает миграция
`0004`, а не этот скрипт (У2) — её применяет шаг 4 через
`migrate-gamification`.

## Разработка

```bash
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format .
.venv/Scripts/python.exe -m pytest
```

Обычный `pytest` docker не требует. Тесты против реальной БД помечены `db` и
запускаются явно вместе с DSN тестовой базы `gamification_test`:

```bash
GAMIFICATION_TEST_DATABASE_URL="postgresql+asyncpg://gamification_app:<пароль>@127.0.0.1:5432/gamification_test" \
GAMIFICATION_TEST_OWNER_DATABASE_URL="postgresql+asyncpg://gamification:<пароль>@127.0.0.1:5432/gamification_test" \
  .venv/Scripts/python.exe -m pytest -m db
```

`GAMIFICATION_TEST_DATABASE_URL` — роль приложения `gamification_app`, под
ней тесты открывают сессии. `GAMIFICATION_TEST_OWNER_DATABASE_URL` — роль
владельца `gamification`, под ней тесты строят схему миграцией (В4=P2).

Базу `gamification_test` создаёт инфраструктурная часть этапа — на момент
написания этого README её ещё нет, поэтому `pytest -m db` без переменной
пропускается с указанием причины, а не падает.

## Ограничения текущего этапа

- Приглашения преподавателей и админов не реализованы: роль в приглашении
  всегда `student`, колонка `role` под них только заложена.
- API управления членствами (приостановка, смена роли) не входит — членство
  можно только создать через приглашение или создание учреждения.
- Валюта, привилегии, XP, лидерборды и показатели учеников — вне зоны этапа.
- Внутреннее API самого gamification пусто: её пока никто не вызывает.
- Каскадное удаление членств при удалении пользователя в users не гарантировано
  — `memberships.user_id` без внешнего ключа, потому что пользователи живут в
  другой базе (I1). Записанный риск, лечится будущим событием `user.deleted`.
