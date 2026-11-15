"""Тесты ограничения частоты входящих запросов (ТЗ п. 11)."""

from __future__ import annotations

import time

from bot.utils.ratelimit import RateLimiter
from bot.webhook_server import _extract_sender_id


def test_allows_up_to_limit() -> None:
    """В пределах ``per_second`` событий пропускаем, дальше — нет."""
    limiter = RateLimiter(per_second=3, burst=10)
    results = [limiter.allow(1) for _ in range(3)]
    assert results == [True, True, True]
    assert limiter.allow(1) is False


def test_separate_users_have_separate_counters() -> None:
    """Флуд одного пользователя не блокирует другого."""
    limiter = RateLimiter(per_second=2, burst=5)
    assert limiter.allow(1)
    assert limiter.allow(1)
    assert limiter.allow(1) is False
    # Другой пользователь — свой счётчик.
    assert limiter.allow(2) is True


def test_window_slides_after_one_second(monkeypatch) -> None:
    """Через секунду окно очищается и запросы снова проходят."""
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now)
    limiter = RateLimiter(per_second=2, burst=5)
    assert limiter.allow(7)
    assert limiter.allow(7)
    assert limiter.allow(7) is False

    # Прошла секунда — окно свободно.
    monkeypatch.setattr(time, "monotonic", lambda: now + 1.01)
    assert limiter.allow(7) is True


def test_burst_grows_to_per_second_minimum() -> None:
    """``burst`` не может быть меньше ``per_second`` (защита от ошибки)."""
    limiter = RateLimiter(per_second=10, burst=1)
    assert all(limiter.allow(5) for _ in range(10))
    assert limiter.allow(5) is False


def test_tracked_keys_grows() -> None:
    """Диагностика: считаем количество активных ключей."""
    limiter = RateLimiter(per_second=5, burst=10)
    limiter.allow(1)
    limiter.allow(2)
    assert limiter.tracked_keys == 2


# --- извлечение user_id из события MAX ------------------------------------


def test_extract_sender_from_message() -> None:
    payload = {"update_type": "message_created", "message": {"sender": {"user_id": 42}}}
    assert _extract_sender_id(payload) == 42


def test_extract_sender_from_callback() -> None:
    payload = {"update_type": "message_callback", "callback": {"user": {"user_id": 7}}}
    assert _extract_sender_id(payload) == 7


def test_extract_sender_from_top_level() -> None:
    assert _extract_sender_id({"user_id": 99}) == 99


def test_extract_sender_none_when_absent() -> None:
    assert _extract_sender_id({}) is None
    assert _extract_sender_id({"update_type": "bot_started"}) is None
    assert _extract_sender_id({"user_id": "not-an-int"}) is None
