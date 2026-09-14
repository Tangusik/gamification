"""Добавить флаг must_change_password к users

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-13

Флаг временного пароля (решение C1, ``.claude/plans/05-admin-features.md``):
ставится при заведении аккаунта преподавателя через
``POST /internal/users`` и снимается сменой пароля через
``PATCH /users/me``. Мягкий флаг — сервер запросы не блокирует.

``server_default false`` — для существующих строк на момент миграции;
новый код всегда пишет значение явно.

Миграция намеренно не импортирует ни модели, ни доменные перечисления:
файл — снимок схемы на момент ревизии, как в ``0001``/``0002``.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Добавить колонку ``must_change_password`` со значением по умолчанию."""
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    """Убрать колонку ``must_change_password``."""
    op.drop_column("users", "must_change_password")
