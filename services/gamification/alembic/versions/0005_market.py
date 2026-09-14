"""Маркет привилегий: каталог, покупки, CHECK на баланс (план 07, Ч1)

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-14

Добавляет ``privileges`` и ``purchases``, ставит на ``currency_balances``
``CHECK (balance >= 0)`` (П3) и заводит два новых вида операций с
валютой — ``purchase``/``purchase_refund`` (без нового типа: ``kind``
по-прежнему ``varchar``, У8 плана 06).

RLS и права роли приложения — по шаблону ``0004`` (этап 07a) и правилу
«каждая ревизия с новой таблицей сама выдаёт GRANT» (У3 плана 07a,
``ALTER DEFAULT PRIVILEGES`` не используется). ``institutions`` и
существующие таблицы этой ревизией не трогаются.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PRIVILEGE_TITLE_LENGTH = 100
PRIVILEGE_DESCRIPTION_LENGTH = 500
PURCHASE_STATUS_LENGTH = 16

# Роль приложения (У1 плана 07a) — та же, что использует 0004; если её
# нет, миграция обязана упасть с понятной причиной (см. 0004).
APP_ROLE = "gamification_app"

# GRANT по фактическому коду (У3 плана 07a): SELECT/INSERT/UPDATE на обе
# новые таблицы, без DELETE (позиции не удаляются, У3 плана 07 — есть
# только is_active; покупки не удаляются вовсе) и без TRUNCATE.
NEW_TABLE_GRANTS: dict[str, str] = {
    "privileges": "SELECT, INSERT, UPDATE",
    "purchases": "SELECT, INSERT, UPDATE",
}

RLS_TABLES: tuple[str, ...] = ("privileges", "purchases")

# То же условие политики, что и в 0004 (У4 плана 07a): NULLIF обязателен
# — иначе после конца транзакции ''::uuid падает с ошибкой приведения
# вместо «0 строк».
INSTITUTION_CTX = (
    "institution_id = NULLIF(current_setting('app.institution_id', true), '')::uuid"
)


def _policy_name(table: str) -> str:
    return f"{table}_institution_isolation"


def upgrade() -> None:
    """Создать таблицы маркета, CHECK на баланс, GRANT и RLS."""
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

    op.create_table(
        "privileges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=PRIVILEGE_TITLE_LENGTH), nullable=False),
        sa.Column(
            "description",
            sa.String(length=PRIVILEGE_DESCRIPTION_LENGTH),
            nullable=True,
        ),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_privileges"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_privileges_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("price > 0", name="ck_privileges_price_positive"),
        sa.CheckConstraint(
            "stock IS NULL OR stock >= 0", name="ck_privileges_stock_non_negative"
        ),
    )
    op.create_index("ix_privileges_institution_id", "privileges", ["institution_id"])

    op.create_table(
        "purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("privilege_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=PRIVILEGE_TITLE_LENGTH), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=PURCHASE_STATUS_LENGTH), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "debit_transaction_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "refund_transaction_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "resolved_by_membership_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.PrimaryKeyConstraint("id", name="pk_purchases"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_purchases_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_purchases_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["privilege_id"],
            ["privileges.id"],
            name="fk_purchases_privilege_id_privileges",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["debit_transaction_id"],
            ["currency_transactions.id"],
            name="fk_purchases_debit_transaction_id_currency_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["refund_transaction_id"],
            ["currency_transactions.id"],
            name="fk_purchases_refund_transaction_id_currency_transactions",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_membership_id"],
            ["memberships.id"],
            name="fk_purchases_resolved_by_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "institution_id",
            "operation_id",
            name="uq_purchases_institution_id_operation_id",
        ),
        sa.UniqueConstraint(
            "debit_transaction_id", name="uq_purchases_debit_transaction_id"
        ),
        sa.UniqueConstraint(
            "refund_transaction_id", name="uq_purchases_refund_transaction_id"
        ),
    )
    op.create_index(
        "ix_purchases_institution_id_status_created_at",
        "purchases",
        ["institution_id", "status", "created_at"],
    )

    # П3: баланс никогда не уходит в минус, ноль допустим. Пункт 5 плана
    # (риск 8) — перед применением на dev-базе выполнена read-only
    # проверка count(*) WHERE balance < 0 = 0 вне этой миграции.
    #
    # Сырой SQL, а не ``op.create_check_constraint``: тот прогоняет
    # переданное имя через naming convention метаданных ещё раз и
    # задваивает префикс (``ck_currency_balances_ck_currency_balances_…``),
    # найдено на прогоне db-тестов. ``sa.CheckConstraint(name=…)`` внутри
    # ``op.create_table`` (см. 0003) этой проблеме не подвержен — там
    # готовое имя используется как есть.
    op.execute(
        "ALTER TABLE currency_balances "
        "ADD CONSTRAINT ck_currency_balances_balance_non_negative "
        "CHECK (balance >= 0)"
    )

    # GRANT — каждая ревизия с новой таблицей сама его выдаёт (У3 плана
    # 07a); ALTER DEFAULT PRIVILEGES не используется.
    for table, privileges in NEW_TABLE_GRANTS.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")

    for table in RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {_policy_name(table)} ON {table}
            FOR ALL
            USING ({INSTITUTION_CTX})
            WITH CHECK ({INSTITUTION_CTX})
            """
        )


def downgrade() -> None:
    """Снести добавленное в обратном порядке (симметрично 0004)."""
    for table in RLS_TABLES:
        op.execute(f"DROP POLICY {_policy_name(table)} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    for table in NEW_TABLE_GRANTS:
        op.execute(f"REVOKE ALL ON {table} FROM {APP_ROLE}")

    # Сырой SQL — тот же приём, что и в upgrade (op.drop_constraint
    # подвержен той же проблеме с naming convention).
    op.execute(
        "ALTER TABLE currency_balances "
        "DROP CONSTRAINT ck_currency_balances_balance_non_negative"
    )

    op.drop_index(
        "ix_purchases_institution_id_status_created_at", table_name="purchases"
    )
    op.drop_table("purchases")

    op.drop_index("ix_privileges_institution_id", table_name="privileges")
    op.drop_table("privileges")
