"""Добавить full_name к users

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12

Имя человека (план 11-user-name, решение владельца): одно поле
``full_name`` без разбивки на части, nullable — ни регистрация, ни
``POST /internal/users`` его не заполняют, правит его только сам
пользователь через ``PATCH /users/me``.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся снимком схемы на момент ревизии, как ``0001``-``0004``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавить nullable-колонку ``full_name``; существующие строки не ломает."""
    op.add_column(
        "users",
        sa.Column("full_name", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Убрать колонку ``full_name``."""
    op.drop_column("users", "full_name")
