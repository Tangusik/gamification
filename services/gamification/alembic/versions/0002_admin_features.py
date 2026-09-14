"""Функции администратора: имена участников, группы (раздел «Ч2» плана)

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-13

Добавляет ``memberships.display_name`` (В4/D1) и таблицы групп (В5/G2:
у ученика может быть несколько групп, поэтому ``group_students`` без
``UNIQUE(membership_id)`` — первичный ключ пара).

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
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

DISPLAY_NAME_LENGTH = 100
GROUP_NAME_LENGTH = 100


def upgrade() -> None:
    """Добавить имена участников и схему групп."""
    op.add_column(
        "memberships",
        sa.Column("display_name", sa.String(length=DISPLAY_NAME_LENGTH), nullable=True),
    )

    op.create_table(
        "groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=GROUP_NAME_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_groups"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_groups_institution_id_institutions",
            ondelete="CASCADE",
        ),
    )
    # Уникальность имени группы без учёта регистра в пределах учреждения
    # (умолчания плана) — функциональный индекс, а не проверка в коде.
    op.create_index(
        "uq_groups_institution_id_lower_name",
        "groups",
        ["institution_id", sa.text("lower(name)")],
        unique=True,
    )

    op.create_table(
        "group_students",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "membership_id", name="pk_group_students"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_students_group_id_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_group_students_membership_id_memberships",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "group_teachers",
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("group_id", "membership_id", name="pk_group_teachers"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
            name="fk_group_teachers_group_id_groups",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id"],
            ["memberships.id"],
            name="fk_group_teachers_membership_id_memberships",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    """Снести добавленное в обратном порядке."""
    op.drop_table("group_teachers")
    op.drop_table("group_students")
    op.drop_index("uq_groups_institution_id_lower_name", table_name="groups")
    op.drop_table("groups")
    op.drop_column("memberships", "display_name")
