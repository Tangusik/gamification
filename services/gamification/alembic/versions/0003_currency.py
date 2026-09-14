"""Валюта: баланс ученика и история операций (Ч1 плана 06)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-13

Добавляет ``currency_transactions`` (история, неизменяема — У4) и
``currency_balances`` (баланс, отдельно от истории — У2). Пространство
``operation_id`` общее для начислений и сторно в пределах учреждения
(В4/I1); ``reverses_id`` уникален — сторнировать запись можно только
один раз (В3/E2).

Триггер ``BEFORE UPDATE OR DELETE`` на ``currency_transactions`` — вторая
опора неизменяемости истории поверх отсутствия методов изменения в
порту (У4). ``DROP TABLE`` его не задевает — не эквивалент ``DELETE``.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRANSACTION_KIND_LENGTH = 32
CURRENCY_COMMENT_LENGTH = 200

TRIGGER_FUNCTION_NAME = "currency_transactions_immutable"
TRIGGER_NAME = "trg_currency_transactions_immutable"


def upgrade() -> None:
    """Создать таблицы валюты и защитить историю триггером."""
    op.create_table(
        "currency_transactions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=TRANSACTION_KIND_LENGTH), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=CURRENCY_COMMENT_LENGTH), nullable=True),
        sa.Column(
            "created_by_membership_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reverses_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_currency_transactions"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_currency_transactions_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_currency_transactions_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["memberships.id"],
            name="fk_currency_transactions_created_by_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reverses_id"],
            ["currency_transactions.id"],
            name="fk_currency_transactions_reverses_id_currency_transactions",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "institution_id",
            "operation_id",
            name="uq_currency_transactions_institution_id_operation_id",
        ),
        sa.UniqueConstraint("reverses_id", name="uq_currency_transactions_reverses_id"),
        sa.CheckConstraint(
            "amount <> 0", name="ck_currency_transactions_amount_not_zero"
        ),
    )
    # История ученика читается новыми сверху (У1) — функциональный индекс
    # с явным порядком, тот же приём, что и у ``lower(name)`` в группах.
    op.create_index(
        "ix_currency_transactions_membership_id_created_at",
        "currency_transactions",
        ["membership_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "currency_balances",
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("balance", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("membership_id", name="pk_currency_balances"),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_currency_balances_membership_id_memberships",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_currency_balances_institution_id_institutions",
            ondelete="CASCADE",
        ),
    )

    # Неизменяемость истории (У4) — второй слой поверх отсутствия методов
    # изменения в порту: даже прямой SQL не сможет поменять или удалить
    # уже записанную операцию.
    op.execute(
        f"""
        CREATE FUNCTION {TRIGGER_FUNCTION_NAME}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'currency_transactions is append-only: % is not allowed',
                TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRIGGER_NAME}
        BEFORE UPDATE OR DELETE ON currency_transactions
        FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION_NAME}();
        """
    )


def downgrade() -> None:
    """Снести добавленное в обратном порядке."""
    op.execute(f"DROP TRIGGER {TRIGGER_NAME} ON currency_transactions")
    op.execute(f"DROP FUNCTION {TRIGGER_FUNCTION_NAME}()")
    op.drop_table("currency_balances")
    op.drop_index(
        "ix_currency_transactions_membership_id_created_at",
        table_name="currency_transactions",
    )
    op.drop_table("currency_transactions")
