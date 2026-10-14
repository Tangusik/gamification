"""Профильное имя на членстве (план 11, этап 2): memberships.profile_name

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12

Добавляет ``memberships.profile_name`` — ``VARCHAR(100) NULL``, кэш-копию
профильного имени пользователя (``users.full_name``), синхронизируемую
из users. Смысл колонки отличается от уже существующей
``memberships.display_name``: ``display_name`` — необязательная
накладка админа учреждения, ``profile_name`` — чужие данные, подтянутые
при создании членства (этап 2) и позже синхронизацией (этап 3, вне
объёма этой миграции). Правило отображения — в домене
(``Membership.effective_name``), не здесь.

Отдельного ``GRANT`` не требуется: право ``INSERT, SELECT, UPDATE`` роли
``gamification_app`` на ``memberships`` выдано в ``0004`` на уровне
таблицы, новая колонка попадает под него автоматически — в этом сервисе
принято, что каждая ревизия сама отвечает за права, поэтому это
проверено, а не предположено по аналогии с ``0006``. RLS-политики
``memberships`` эта миграция не меняет: обновление ``profile_name`` по
смене имени в профиле поверх всех учреждений — отдельная задача (этап 3).

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROFILE_NAME_LENGTH = 100


def upgrade() -> None:
    """Добавить nullable-колонку кэша профильного имени."""
    op.add_column(
        "memberships",
        sa.Column("profile_name", sa.String(length=PROFILE_NAME_LENGTH), nullable=True),
    )


def downgrade() -> None:
    """Удалить колонку кэша профильного имени."""
    op.drop_column("memberships", "profile_name")
