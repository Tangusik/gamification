"""Синхронизация profile_name поверх учреждений (план 11, этап 3).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12

Users сообщает «имя в профиле изменилось» через служебный эндпоинт
``PATCH /internal/memberships/profile-name``, и gamification обязан
обновить ``memberships.profile_name`` сразу во всех учреждениях этого
пользователя (этап 3 плана 11). Эта операция межарендная по смыслу —
учреждение, в котором лежит членство, заранее не известно, — а
действующая политика ``memberships_institution_isolation`` (``0004``)
держит ``WITH CHECK (institution_ctx)`` строгим: без контекста
учреждения такой ``UPDATE`` падает на проверке.

Решение ведущего задачи — не расширять существующий ``WITH CHECK``
(это ослабило бы его для всех операций), а завести **вторую,
permissive**-политику под отдельную служебную переменную сессии
(``app.profile_sync_user_id``). Permissive-политики на одну команду
складываются через ``OR`` (документированное поведение PostgreSQL),
поэтому путь синхронизации открывается только тогда, когда эта
переменная выставлена, а действующая политика не ослабляется ни на
бит. ``NULLIF`` обязателен по той же причине, что и в ``0004``: без
него сессия, не выставившая переменную, получила бы ошибку приведения
``''::uuid`` вместо «0 строк» (fail-closed без диагностики).

Отдельный ``GRANT`` не требуется: право ``UPDATE`` роли
``gamification_app`` на ``memberships`` выдано ещё в ``0004`` на
уровне таблицы — вторая политика ограничивает *какие строки* видны
для записи, а не то, есть ли у роли сама привилегия ``UPDATE``.

Цена решения (зафиксировать прямо, не прятать): RLS не умеет
ограничивать, какую именно колонку правит ``UPDATE`` — политика
проверяет только видимость строки, а не список изменяемых полей.
Дисциплину «эта переменная открывает запись только в ``profile_name``»
держит не база, а единственное место в коде —
``SqlAlchemyUserMemberships.set_profile_name`` (там же, где переменная
выставляется). Расширять использование ``app.profile_sync_user_id`` на
любые другие операции нельзя: это разрушит ровно то предположение, на
котором держится безопасность эндпоинта синхронизации.

Миграция намеренно не импортирует ни модели, ни доменные перечисления —
файл остаётся воспроизводимым снимком схемы на момент ревизии.
"""

from collections.abc import Sequence

from alembic import op

# Идентификаторы ревизии, используемые alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY_NAME = "memberships_profile_name_sync"

PROFILE_SYNC_CONDITION = (
    "user_id = NULLIF(current_setting('app.profile_sync_user_id', true), '')::uuid"
)


def upgrade() -> None:
    """Добавить вторую permissive-политику под служебную переменную."""
    op.execute(
        f"""
        CREATE POLICY {POLICY_NAME} ON memberships
        FOR UPDATE
        USING ({PROFILE_SYNC_CONDITION})
        WITH CHECK ({PROFILE_SYNC_CONDITION})
        """
    )


def downgrade() -> None:
    """Снять политику синхронизации профильного имени."""
    op.execute(f"DROP POLICY {POLICY_NAME} ON memberships")
