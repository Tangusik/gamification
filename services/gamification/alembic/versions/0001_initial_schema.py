"""Целевая схема сервиса gamification: institutions, memberships, invitations

Revision ID: 0001
Revises:
Create Date: 2026-09-11

Первая миграция создаёт учреждения, членства и приглашения (разделы 3 и
5 плана; этапы 3 и 4 уходят одним релизом, поэтому ревизия одна — эта
ещё не применена ни на одном стенде).

Миграция намеренно не импортирует ни модели, ни доменные перечисления:
файл — снимок схемы на момент ревизии, модели меняются дальше.
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
# ALTER TYPE в проде.
ENUM_LENGTH = 32

# Длина колонки токена приглашения — с запасом к
# ``secrets.token_urlsafe(32)`` (обычно 43 символа).
TOKEN_LENGTH = 64


def upgrade() -> None:
    """Создать таблицы учреждений, приглашений и членств."""
    op.create_table(
        "institutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_institutions"),
    )

    op.create_table(
        "invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Токен хранится открыто (F5, решение владельца против
        # рекомендации): нужен для перепечатки QR.
        sa.Column("token", sa.String(length=TOKEN_LENGTH), nullable=False),
        sa.Column("role", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses_count", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # NULL — не отозвано; срока жизни нет (F1), отзыв только вручную.
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_invitations"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_invitations_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("token", name="uq_invitations_token"),
    )
    op.create_index("ix_invitations_institution_id", "invitations", ["institution_id"])

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # Без внешнего ключа: пользователи живут в базе users (I1).
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("status", sa.String(length=ENUM_LENGTH), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Приглашение, по которому пришёл участник; NULL — заведено
        # иначе (например, создатель учреждения).
        sa.Column("invitation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_memberships_institution_id_institutions",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["invitations.id"],
            name="fk_memberships_invitation_id_invitations",
            ondelete="SET NULL",
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

    Порядок обратный созданию: memberships ссылается на institutions и
    на invitations, invitations — на institutions.
    """
    op.drop_index("ix_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("ix_invitations_institution_id", table_name="invitations")
    op.drop_table("invitations")
    op.drop_table("institutions")
