"""Даты и периоды в часовом поясе пользователя (ТЗ п. 3.6–3.8).

Все «сегодня/вчера/неделя/месяц» считаются в часовом поясе пользователя,
а не в UTC сервера. Хранится локальная дата операции (``date``), поэтому
отчёты не «съезжают» при смене пояса.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bot.constants import DEFAULT_TIMEZONE


def user_tz(name: str | None) -> ZoneInfo:
    """Часовой пояс пользователя с безопасным fallback."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_in_tz(name: str | None) -> datetime:
    """Текущее время в поясе пользователя."""
    return datetime.now(user_tz(name))


def today_in_tz(name: str | None) -> date:
    return now_in_tz(name).date()


def period_of(value: date) -> str:
    """Период ``YYYY-MM`` для даты (используется в бюджетах)."""
    return f"{value.year:04d}-{value.month:02d}"


def current_period(tz_name: str | None = None) -> str:
    return period_of(today_in_tz(tz_name))


def previous_period(period: str) -> str:
    """Предыдущий месяц для ``YYYY-MM``."""
    year, month = (int(part) for part in period.split("-"))
    if month == 1:
        return f"{year - 1:04d}-12"
    return f"{year:04d}-{month - 1:02d}"


def period_bounds(period: str) -> tuple[date, date]:
    """Границы месяца ``YYYY-MM`` → ``(первое число, последнее число)``."""
    year, month = (int(part) for part in period.split("-"))
    start = date(year, month, 1)
    end = date(year, 12, 31) if month == 12 else date(year, month + 1, 1) - timedelta(days=1)
    return start, end


@dataclass(frozen=True, slots=True)
class DateRange:
    """Границы периода выборки."""

    start: date
    end: date
    label: str

    def contains(self, value: date) -> bool:
        return self.start <= value <= self.end


def today_range(tz_name: str | None = None) -> DateRange:
    today = today_in_tz(tz_name)
    return DateRange(today, today, "Сегодня")


def yesterday_range(tz_name: str | None = None) -> DateRange:
    day = today_in_tz(tz_name) - timedelta(days=1)
    return DateRange(day, day, "Вчера")


def week_range(tz_name: str | None = None) -> DateRange:
    """Последние 7 дней, включая сегодня."""
    today = today_in_tz(tz_name)
    return DateRange(today - timedelta(days=6), today, "Последние 7 дней")


def month_range(tz_name: str | None = None) -> DateRange:
    today = today_in_tz(tz_name)
    start = today.replace(day=1)
    return DateRange(start, today, f"Текущий месяц ({start:%m.%Y})")


def custom_range(start: date, end: date) -> DateRange:
    if start > end:
        start, end = end, start
    return DateRange(start, end, f"{start:%d.%m.%Y} — {end:%d.%m.%Y}")


def parse_date_ru(text: str, *, tz_name: str | None = None) -> date | None:
    """Разобрать дату: ``06.11.2026``, ``6.11``, ``2026-11-06``, ``сегодня``, ``вчера``."""
    raw = (text or "").strip().lower()
    today = today_in_tz(tz_name)
    if raw in {"сегодня", "today", "сейчас"}:
        return today
    if raw in {"вчера", "yesterday"}:
        return today - timedelta(days=1)
    if raw in {"позавчера"}:
        return today - timedelta(days=2)

    for fmt in ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    # Формат без года: 6.11 → текущий год (или прошлый год, если дата в будущем).
    for fmt in ("%d.%m", "%d/%m"):
        try:
            parsed = datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
        candidate = parsed.replace(year=today.year)
        if candidate > today:
            candidate = candidate.replace(year=today.year - 1)
        return candidate
    return None


#: Периоды истории, доступные кнопками (ТЗ п. 3.7).
HISTORY_PERIODS: tuple[tuple[str, str], ...] = (
    ("today", "Сегодня"),
    ("yesterday", "Вчера"),
    ("week", "7 дней"),
    ("month", "Месяц"),
    ("custom", "Свой период"),
)


def range_by_key(key: str, tz_name: str | None = None) -> DateRange:
    """Период по ключу из кнопок истории."""
    if key == "today":
        return today_range(tz_name)
    if key == "yesterday":
        return yesterday_range(tz_name)
    if key == "week":
        return week_range(tz_name)
    return month_range(tz_name)
