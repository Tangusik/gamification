"""Целевая схема сервиса users: users, institutions, memberships

Revision ID: 0001
Revises:
Create Date: 2026-09-10

Первая миграция создаёт **целевую** схему сразу, без промежуточной
формы с ролью на пользователе: продовых данных нет, мигрировать нечего.

Миграция намеренно не импортирует ни модели, ни доменные перечисления.
Файл — снимок схемы на момент ревизии; модели меняются дальше, а
применённая миграция обязана остаться воспроизводимой.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Значения перечислений хранятся строками, а не native-типом
# PostgreSQL: добавление роли или статуса не должно требовать
# ALTER TYPE в проде. По той же причине нет и CHECK-ограничения —
# оно вернуло бы ту же проблему через заднюю дверь.
ENUM_LENGTH = 32


def upgrade() -> None:
    """Создать таблицы пользователей, учреждений и членств."""
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    # Индекс от базового класса fastapi-users: регистрозависимый.
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    # Уникальность без учёта регистра. Обязательное требование
    # knowledge/users-service/02-storage-seam.md: адаптер ищет через
    # lower(email), и без этого индекса two@x и TWO@X сосуществовали
    # бы, а поиск возвращал бы произвольного из двух. Индексы
    # сосуществуют — верхний закрывает точное совпадение, этот регистр.
    op.create_index(
        "ix_users_email_lower",
        "users",
        [sa.text("lower(email)")],
        unique=True,
    )

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
        # Второе членство в том же учреждении сделало бы выбор роли
        # неоднозначным.
        sa.UniqueConstraint(
            "user_id",
            "institution_id",
            name="uq_memberships_user_id_institution_id",
        ),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])


def downgrade() -> None:
    """Снести схему целиком.

    Порядок обратный созданию: memberships ссылается на обе таблицы.
    """
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("institutions")
    op.drop_index("ix_users_email_lower", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
