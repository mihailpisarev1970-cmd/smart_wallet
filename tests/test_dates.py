"""Тесты периодов и дат (ТЗ п. 3.6–3.8)."""

from __future__ import annotations

from datetime import date, timedelta

from bot.utils.dates import (
    current_period,
    custom_range,
    month_range,
    parse_date_ru,
    period_bounds,
    previous_period,
    today_range,
    week_range,
    yesterday_range,
)


def test_parse_date_ru_formats() -> None:
    assert parse_date_ru("06.11.2026") == date(2026, 11, 6)
    assert parse_date_ru("2026-11-06") == date(2026, 11, 6)
    assert parse_date_ru("6.11.2026") == date(2026, 11, 6)


def test_parse_date_ru_relative(tz_name: str = "Europe/Moscow") -> None:
    today = today_range(tz_name).start
    assert parse_date_ru("сегодня") == today
    assert parse_date_ru("вчера") == today - timedelta(days=1)
    assert parse_date_ru("позавчера") == today - timedelta(days=2)


def test_parse_date_ru_invalid() -> None:
    assert parse_date_ru("не дата") is None
    assert parse_date_ru("") is None


def test_week_range_is_seven_days_ending_today() -> None:
    rng = week_range("Europe/Moscow")
    assert (rng.end - rng.start).days == 6
    assert rng.end == today_range("Europe/Moscow").end


def test_yesterday_range() -> None:
    rng = yesterday_range("Europe/Moscow")
    assert rng.start == rng.end == today_range("Europe/Moscow").start - timedelta(days=1)


def test_month_range_starts_on_first_day() -> None:
    rng = month_range("Europe/Moscow")
    assert rng.start.day == 1


def test_period_helpers() -> None:
    assert current_period("Europe/Moscow").count("-") == 1
    assert previous_period("2026-01") == "2025-12"
    assert previous_period("2026-11") == "2026-10"
    start, end = period_bounds("2026-02")
    assert start == date(2026, 2, 1)
    assert end == date(2026, 2, 28)
    _, leap_end = period_bounds("2024-02")
    assert leap_end == date(2024, 2, 29)


def test_custom_range_swaps_bounds() -> None:
    rng = custom_range(date(2026, 11, 10), date(2026, 11, 1))
    assert rng.start == date(2026, 11, 1)
    assert rng.end == date(2026, 11, 10)
    assert rng.contains(date(2026, 11, 5))
