"""Внутренний роутер gamification.

Пуст: в этом этапе gamification никто не вызывает (раздел 6 плана —
внутреннее API gamification в этапе пусто; у users появляется
``POST /internal/tokens/institution-context``, но это его роутер, не
этот). Заведён заранее, чтобы карта адресов
(``app/api/main_router.py``) не менялась при появлении первого
внутреннего вызова.
"""

from fastapi import APIRouter

router = APIRouter()
