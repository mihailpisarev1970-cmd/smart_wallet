"""Форматирование текстов сообщений и дат.

MAX поддерживает HTML-разметку через ``format="html"``: ``<b>``, ``<i>``,
``<u>``, ``<s>``, ``<code>``, ``<a href>``. Моноширинный блок удобно
делать через ``<pre>`` для таблиц статистики.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from decimal import Decimal

from bot.constants import CURRENCY_SYMBOLS

MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)

MONTHS_NOMINATIVE = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)

WEEKDAYS_SHORT = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")


def escape_html(text: str | None) -> str:
    """Экранировать пользовательский текст для ``format="html"``."""
    return html.escape(text or "", quote=False)


def bold(text: str) -> str:
    return f"<b>{text}</b>"


def italic(text: str) -> str:
    return f"<i>{text}</i>"


def code(text: str) -> str:
    return f"<code>{escape_html(text)}</code>"


def pre(text: str) -> str:
    """Моноширинный блок (для таблиц)."""
    return f"<pre>{escape_html(text)}</pre>"


def format_date_ru(value: date | datetime, *, with_year: bool = True, short: bool = False) -> str:
    """Дата по-русски: ``6 ноября 2026`` или ``06.11.2026``."""
    if short:
        return value.strftime("%d.%m.%Y" if with_year else "%d.%m")
    day = value.day
    month = MONTHS_GENITIVE[value.month - 1]
    return f"{day} {month} {value.year}" if with_year else f"{day} {month}"


def format_period_ru(period: str) -> str:
    """``2026-11`` → ``Ноябрь 2026``."""
    try:
        year, month = period.split("-")
        return f"{MONTHS_NOMINATIVE[int(month) - 1]} {year}"
    except (ValueError, IndexError):
        return period


def currency_symbol(currency: str) -> str:
    return CURRENCY_SYMBOLS.get(currency, currency)


def format_amount(amount: Decimal | int | str, currency: str = "RUB") -> str:
    """Сумма с валютой: ``1 500 ₽``."""
    from bot.utils.money import format_money

    return format_money(amount, currency=currency)


def progress_bar(percent: float, *, width: int = 12) -> str:
    """Текстовый индикатор прогресса: ``██████░░░░░░ 52%``."""
    percent = max(0.0, min(100.0, percent))
    filled = round(width * percent / 100)
    return f"{'█' * filled}{'░' * (width - filled)} {percent:.0f}%"


def plural_ru(number: int, one: str, few: str, many: str) -> str:
    """Склонение существительного: ``1 операция``, ``3 операции``, ``5 операций``."""
    number = abs(number) % 100
    if 11 <= number <= 19:
        return many
    last = number % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def sign(value: Decimal | int | float) -> str:
    """Знак числа для отображения (``+``/``−``)."""
    return "−" if Decimal(str(value)) < 0 else "+"
