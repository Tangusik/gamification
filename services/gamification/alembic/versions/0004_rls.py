"""RLS и разделение ролей PostgreSQL (этап 07a, план `.claude/plans/07a-rls.md`)

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-14

Всё, что относится к схеме (У2 плана): ``GRANT`` роли приложения
``gamification_app``, политики RLS и триггер, запрещающий ``TRUNCATE`` на
истории валюты. Роль и её пароль — забота init-скрипта кластера
(``deploy/postgres/init/02-create-gamification-db.sh``), здесь их не
создаём и не трогаем при ``downgrade`` (У6): роль — объект кластера, а
не схемы.

На ``institutions`` RLS нет (В2/I0 плана): в таблице нет
``institution_id`` — сама эта таблица является арендатором, изоляцию по
ней держит H1 в коде.

Межарендные исключения В1/X1: у ``memberships`` политика на чтение
дополнительно пускает собственные членства пользователя
(``app.user_id``), у ``invitations`` — приглашение по предъявленному
токену (``app.invitation_token``). ``WITH CHECK`` у обеих остаётся
строгим — только по ``app.institution_id``: расширение X1 касается
только видимости чтения, запись в чужое учреждение не нужна ни одному
сценарию (цена X1, раздел 2 плана).

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Роль приложения (У1 плана): заводит init-скрипт кластера, здесь только
# используется по имени. Если её нет — том не прошёл ручной шаг
# (``services/gamification/README.md``), и миграция обязана упасть с
# понятной причиной, а не тихим ``GRANT`` в никуда.
APP_ROLE = "gamification_app"

# Триггер неизменяемости истории валюты (миграция 0003) — этой же
# функцией закрывается и `TRUNCATE` (У5): `BEFORE UPDATE OR DELETE`
# ловит построчные изменения, но не ловит `TRUNCATE`, а `У1`
# (владелец таблиц — не приложение) не мешает суперпользователю или
# самому владельцу отключить триггер и обойти его.
CURRENCY_TRIGGER_FUNCTION = "currency_transactions_immutable"
CURRENCY_TRUNCATE_TRIGGER = "trg_currency_transactions_immutable_truncate"

# `GRANT` по фактическому коду (У3): не по шаблону "всё, что есть у
# модели", а по тому, какие команды использует репозиторий. Общий
# `ALTER DEFAULT PRIVILEGES` не применяется — будущая таблица истории
# иначе молча получила бы `DELETE` (риск 8 плана; правило — каждая
# новая ревизия сама выдаёт `GRANT`, начиная с `0005` маркета).
TABLE_GRANTS: dict[str, str] = {
    "institutions": "SELECT, INSERT, UPDATE",
    "memberships": "SELECT, INSERT, UPDATE",
    "invitations": "SELECT, INSERT, UPDATE",
    "currency_balances": "SELECT, INSERT, UPDATE",
    "groups": "SELECT, INSERT, UPDATE, DELETE",
    "group_students": "SELECT, INSERT, DELETE",
    "group_teachers": "SELECT, INSERT, DELETE",
    # Только SELECT, INSERT: в коде на currency_transactions нет ни
    # UPDATE, ни DELETE, ни TRUNCATE (история неизменяема, У4/У5).
    "currency_transactions": "SELECT, INSERT",
}

# Таблицы с ENABLE/FORCE ROW LEVEL SECURITY — 5 таблиц с институтом плюс
# 2 таблицы связей (У4). `institutions` сюда не входит (В2/I0).
RLS_TABLES: tuple[str, ...] = (
    "memberships",
    "invitations",
    "groups",
    "currency_transactions",
    "currency_balances",
    "group_students",
    "group_teachers",
)

# Общее условие политики (У4): ``NULLIF`` обязателен — после конца
# транзакции (или для сессии, ни разу не выставившей переменную) она
# читается как пустая строка/NULL, и без NULLIF `''::uuid` падает с
# ошибкой приведения вместо «0 строк» (fail-closed без диагностики).
INSTITUTION_CTX = (
    "institution_id = NULLIF(current_setting('app.institution_id', true), '')::uuid"
)


def _grant_statements() -> list[str]:
    statements = [f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}"]
    for table, privileges in TABLE_GRANTS.items():
        statements.append(f"GRANT {privileges} ON {table} TO {APP_ROLE}")
    return statements


def _revoke_statements() -> list[str]:
    statements = [f"REVOKE ALL ON {table} FROM {APP_ROLE}" for table in TABLE_GRANTS]
    statements.append(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    return statements


def _policy_name(table: str) -> str:
    return f"{table}_institution_isolation"


def upgrade() -> None:
    """Выдать права роли приложения и включить RLS по схеме У2–У6."""
    connection = op.get_bind()
    role_exists = connection.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"),
        {"role": APP_ROLE},
    ).scalar()
    if not role_exists:
        raise RuntimeError(
            f"Роль {APP_ROLE!r} не найдена в кластере. На пустом томе её "
            "создаёт deploy/postgres/init/02-create-gamification-db.sh; на "
            "существующем томе нужен ручной шаг из "
            "services/gamification/README.md, раздел «База данных в "
            "существующем томе», прежде чем применять эту миграцию."
        )

    for statement in _grant_statements():
        op.execute(statement)

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE — иначе владелец таблиц (роль gamification, под которой
        # идёт сама миграция) видел бы все строки в обход политики; для
        # неё это неважно на рантайме (приложение ходит под
        # gamification_app), но упрощает проверку в тестах и на dev-базе.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # memberships: X1 — сверх собственного учреждения видны свои же
    # членства в любых учреждениях (по app.user_id), а не только в
    # текущем контексте. WITH CHECK остаётся строгим (только ctx) — цена
    # X1 в плане: расширение касается только чтения.
    op.execute(
        f"""
        CREATE POLICY {_policy_name("memberships")} ON memberships
        FOR ALL
        USING (
            {INSTITUTION_CTX}
            OR user_id = NULLIF(current_setting('app.user_id', true), '')::uuid
        )
        WITH CHECK ({INSTITUTION_CTX})
        """
    )

    # invitations: X1 — приглашение видно и по предъявленному токену
    # (принятие приглашения не знает контекста учреждения заранее).
    # WITH CHECK строгий по тем же причинам, что и у memberships.
    op.execute(
        f"""
        CREATE POLICY {_policy_name("invitations")} ON invitations
        FOR ALL
        USING (
            {INSTITUTION_CTX}
            OR token = NULLIF(current_setting('app.invitation_token', true), '')
        )
        WITH CHECK ({INSTITUTION_CTX})
        """
    )

    for table in ("groups", "currency_transactions", "currency_balances"):
        op.execute(
            f"""
            CREATE POLICY {_policy_name(table)} ON {table}
            FOR ALL
            USING ({INSTITUTION_CTX})
            WITH CHECK ({INSTITUTION_CTX})
            """
        )

    # Таблицы связей без своего institution_id (У4) — условие идёт через
    # EXISTS по groups, у которой уже есть собственная политика; строка
    # видна, только если её группа принадлежит текущему учреждению.
    for table in ("group_students", "group_teachers"):
        exists_clause = (
            f"EXISTS (SELECT 1 FROM groups g WHERE g.id = {table}.group_id "
            "AND g.institution_id = NULLIF(current_setting('app.institution_id', "
            "true), '')::uuid)"
        )
        op.execute(
            f"""
            CREATE POLICY {_policy_name(table)} ON {table}
            FOR ALL
            USING ({exists_clause})
            WITH CHECK ({exists_clause})
            """
        )

    # У5: TRUNCATE не ловится триггером BEFORE UPDATE OR DELETE (0003) —
    # без этого владелец таблиц (или суперпользователь) мог бы стереть
    # историю в обход неизменяемости, не трогая ни одной строки построчно.
    op.execute(
        f"""
        CREATE TRIGGER {CURRENCY_TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON currency_transactions
        FOR EACH STATEMENT EXECUTE FUNCTION {CURRENCY_TRIGGER_FUNCTION}()
        """
    )


def downgrade() -> None:
    """Снять триггер, политики, FORCE/ENABLE и GRANT (У6). Роль остаётся."""
    op.execute(f"DROP TRIGGER {CURRENCY_TRUNCATE_TRIGGER} ON currency_transactions")

    for table in RLS_TABLES:
        op.execute(f"DROP POLICY {_policy_name(table)} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for statement in _revoke_statements():
        op.execute(statement)
