"""Тест формата ключа denylist отозванных токенов."""

from gamification_auth import denylist_key


def test_denylist_key_matches_users_format() -> None:
    """Формат совпадает с тем, что раньше жил в услугах users напрямую.

    ``services/users/app/repositories/denylist.py`` использует эту
    функцию из библиотеки.
    """
    assert denylist_key("11111111-2222-4333-8444-555555555555") == (
        "users:denylist:jti:11111111-2222-4333-8444-555555555555"
    )


def test_denylist_key_is_a_pure_function() -> None:
    """Одна и та же строка ``jti`` всегда даёт один и тот же ключ."""
    assert denylist_key("abc") == denylist_key("abc")
