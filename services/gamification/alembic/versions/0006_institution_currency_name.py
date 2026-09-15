"""Название валюты учреждения (В5): institutions.currency_name

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-14

Добавляет ``institutions.currency_name`` — ``VARCHAR(32) NULL``, без
значения по умолчанию: ``NULL`` значит «не задано», фронт в этом случае
показывает запасное слово сам.

Отдельного ``GRANT`` не требуется: право ``UPDATE`` роли
``gamification_app`` на ``institutions`` выдано в ``0004`` на уровне
таблицы (``GRANT SELECT, INSERT, UPDATE ON institutions``, не постолбцово),
новая колонка попадает под него автоматически. RLS на ``institutions`` не
заводился и не заводится этой миграцией (В2/I0, `01-structure.md`) — в
таблице по-прежнему нет ``institution_id``.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CURRENCY_NAME_LENGTH = 32


def upgrade() -> None:
    """Добавить nullable-колонку названия валюты учреждения."""
    op.add_column(
        "institutions",
        sa.Column(
            "currency_name", sa.String(length=CURRENCY_NAME_LENGTH), nullable=True
        ),
    )


def downgrade() -> None:
    """Удалить колонку названия валюты учреждения."""
    op.drop_column("institutions", "currency_name")
