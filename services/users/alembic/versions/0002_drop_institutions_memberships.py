"""Удалить institutions и memberships: переехали в сервис gamification

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-11

Учреждения и членства (роль, статус) стали ответственностью
gamification (``.claude/plans/03-gamification-service.md``, раздел 1):
она заводит собственные таблицы с той же формой. users сохраняет
личность, аутентификацию и внутренний выпуск токена в контексте,
принесённом gamification, но больше не хранит ни одной из этих таблиц.

**Данные не переносятся.** По состоянию на дату ревизии деплойная база
не содержала записей (см. `04-progress.md`), поэтому ``upgrade`` просто
удаляет обе таблицы. ``downgrade`` восстанавливает только **пустую
структуру** — ту же, что создавала ``0001``, — а не данные: их взять
неоткуда, миграция необратима по содержимому.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_LENGTH = 32


def upgrade() -> None:
    """Удалить memberships и institutions; users не затрагивается.

    Порядок обратный созданию в ``0001``: ``memberships`` ссылается на
    обе таблицы через внешние ключи.
    """
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("institutions")


def downgrade() -> None:
    """Восстановить пустую структуру обеих таблиц — без данных.

    Снимок совпадает с тем, что создавала ``0001``: имена ограничений,
    типы и длины колонок те же, только пустые.
    """
    op.create_table(
        "institutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_institutions"),
    )

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("status", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_memberships_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "user_id",
            "institution_id",
            name="uq_memberships_user_id_institution_id",
        ),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
