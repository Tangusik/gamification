"""Добавить refresh_sessions и refresh_tokens

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-15

Схема для плана 10-refresh (У1): одна сессия — одна цепочка
refresh-токенов одного клиента (``web``/``mobile``) одного пользователя.

``refresh_tokens.token_hash`` хранит SHA-256 сырого токена (64 hex
символа), сам сырой токен нигде не хранится. Хранится вся цепочка, а не
только предыдущий токен: без этого вор, дважды провернувший ротацию,
остаётся незамеченным, когда пользователь предъявит старый токен.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся снимком схемы на момент ревизии, как ``0001``-``0003``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Создать таблицы refresh-сессий и их токенов."""
    op.create_table(
        "refresh_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("client", sa.String(length=16), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(length=32), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_sessions"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_refresh_sessions_user_id_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_refresh_sessions_user_id", "refresh_sessions", ["user_id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_hash", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("token_hash", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["refresh_sessions.id"],
            name="fk_refresh_tokens_session_id_refresh_sessions",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"])


def downgrade() -> None:
    """Снести обе таблицы.

    Порядок обратный созданию: ``refresh_tokens`` ссылается на
    ``refresh_sessions``.
    """
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_refresh_sessions_user_id", table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
