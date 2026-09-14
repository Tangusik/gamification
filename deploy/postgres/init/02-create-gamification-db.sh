#!/bin/sh
# Роль и базы сервиса gamification (I1): отдельная роль gamification,
# отдельные базы gamification / gamification_test, без доступа к базе
# users, где лежат хеши паролей.
#
# Скрипт — .sh, а не .sql: пароль роли берётся из переменной окружения
# GAMIFICATION_DB_PASSWORD, а SQL-файл окружение читать не умеет.
#
# Как и 01-create-test-db.sql, отрабатывает только на пустом томе
# postgres-data — это стандартное поведение образа postgres
# (docker-entrypoint-initdb.d выполняется один раз, при первичной
# инициализации кластера). На уже существующем томе шаг нужно
# выполнить вручную — см. services/gamification/README.md, раздел
# «База данных в существующем томе».
#
# Идемпотентность: скрипт можно запустить повторно вручную на одном и
# том же кластере — CREATE ROLE/DATABASE пропускаются, если объект уже
# существует.
set -eu

: "${GAMIFICATION_DB_PASSWORD:?GAMIFICATION_DB_PASSWORD is required}"
: "${GAMIFICATION_APP_DB_PASSWORD:?GAMIFICATION_APP_DB_PASSWORD is required}"

# L1: одинаковый пароль у владельца и у роли приложения даёт входу под
# gamification_app доступ под ролью-владельцем таблиц — RLS перестаёт
# защищать от собственных ошибок в коде приложения. Сравнение без
# вывода значений в сообщение об ошибке.
if [ "$GAMIFICATION_DB_PASSWORD" = "$GAMIFICATION_APP_DB_PASSWORD" ]; then
  echo "GAMIFICATION_DB_PASSWORD and GAMIFICATION_APP_DB_PASSWORD must differ" >&2
  exit 1
fi

# Пароль psql читает из окружения через \getenv, а не через аргумент
# -v: аргументы psql видны в списке процессов контейнера (ps ax), а
# \getenv читает переменную окружения самого процесса psql, минуя
# argv. \gexec, а не DO $$ ... $$: psql не подставляет :'pw' внутри
# доллар-кавычек.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv pw GAMIFICATION_DB_PASSWORD

SELECT format(
    'ALTER ROLE gamification WITH LOGIN PASSWORD %L',
    :'pw'
)
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gamification')
\gexec

SELECT format(
    'CREATE ROLE gamification WITH LOGIN PASSWORD %L',
    :'pw'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gamification')
\gexec

-- gamification_app (У1) — роль приложения под RLS (0004): без прав
-- владельца схемы и таблиц, без обхода RLS. NOREPLICATION (L3) —
-- у роли приложения нет причин читать WAL, а REPLICATION даёт доступ
-- к данным в обход политик RLS. Атрибуты выставляются и при ALTER на
-- повторном запуске, чтобы не разъехаться, если их когда-то поменяли
-- вручную.
\getenv app_pw GAMIFICATION_APP_DB_PASSWORD

SELECT format(
    'ALTER ROLE gamification_app WITH LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'app_pw'
)
WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gamification_app')
\gexec

SELECT format(
    'CREATE ROLE gamification_app WITH LOGIN PASSWORD %L NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION',
    :'app_pw'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gamification_app')
\gexec
SQL

# CREATE DATABASE не выполняется внутри DO/транзакции, поэтому
# используется psql \gexec: он строит и выполняет CREATE DATABASE
# только если базы ещё нет.
#
# Имя основной базы кластера берётся из POSTGRES_DB (compose позволяет
# его переопределить), а не зашито строкой "users": на пустом томе с
# другим POSTGRES_DB REVOKE по имени "users" упал бы после создания
# роли и прервал init без повторного запуска при рестарте контейнера.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" <<'SQL'
SELECT 'CREATE DATABASE gamification OWNER gamification'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'gamification')
\gexec

SELECT 'CREATE DATABASE gamification_test OWNER gamification'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'gamification_test')
\gexec

-- gamification_app подключается к обеим базам gamification (табличные
-- GRANT и политики RLS — забота миграции 0004, а не этого скрипта,
-- см. У2). GRANT выполняется после CREATE DATABASE: без него команда
-- упала бы на несуществующей базе на пустом томе.
GRANT CONNECT ON DATABASE gamification, gamification_test TO gamification_app;

-- По умолчанию PUBLIC может подключаться к любой базе кластера.
-- Без явного отзыва роль gamification подключилась бы и к основной
-- базе кластера, где лежат хеши паролей users — критерий
-- "gamification не подключается к users" тогда не выполняется.
-- Суперпользователь (POSTGRES_USER) CONNECT-привилегией не
-- пользуется и не страдает от отзыва у PUBLIC. :"db" — подстановка
-- идентификатора psql, имя берётся из POSTGRES_DB, а не зашито.
REVOKE CONNECT ON DATABASE :"db" FROM PUBLIC;
SQL

# users_test существует только в dev-инициализации (01-create-test-db.sql
# монтируется целиком лишь в docker-compose.dev.yml); в деплое базы
# users_test нет, и REVOKE на неё завершился бы ошибкой. Отзываем
# отдельно и только если база есть.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
SELECT 'REVOKE CONNECT ON DATABASE users_test FROM PUBLIC'
WHERE EXISTS (SELECT 1 FROM pg_database WHERE datname = 'users_test')
\gexec
SQL
