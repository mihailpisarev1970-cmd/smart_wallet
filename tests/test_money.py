"""Тесты разбора и форматирования денежных сумм (ТЗ п. 7.2)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bot.utils.money import (
    MAX_AMOUNT,
    format_money,
    parse_amount,
    to_decimal,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1500", "1500.00"),
        ("1 500", "1500.00"),
        ("1 500,50", "1500.50"),
        ("1250.5", "1250.50"),
        ("1.500,50", "1500.50"),
        ("15к", "15000.00"),
        ("15K", "15000.00"),
        ("2,5 тыс", "2500.00"),
        ("1200р", "1200.00"),
        ("Потратил 1250 на продукты", "1250.00"),
        ("Кофе 320 руб", "320.00"),
    ],
)
def test_parse_amount_accepts_human_input(text: str, expected: str) -> None:
    parsed = parse_amount(text)
    assert parsed is not None, f"не разобрано: {text!r}"
    assert parsed.amount == Decimal(expected)


@pytest.mark.parametrize(
    "text",
    ["", None, "без числа", "0", "-100", "abc", "10" * 20],
)
def test_parse_amount_rejects_invalid(text: str | None) -> None:
    assert parse_amount(text) is None


def test_parse_amount_uses_decimal_not_float() -> None:
    parsed = parse_amount("0,1")
    assert parsed is not None
    assert isinstance(parsed.amount, Decimal)
    assert parsed.amount + parsed.amount + parsed.amount == Decimal("0.30")


def test_to_decimal_rounds_half_up() -> None:
    assert to_decimal("10.005") == Decimal("10.01")
    assert to_decimal(0.1) == Decimal("0.10")


def test_to_decimal_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        to_decimal("не сумма")


@pytest.mark.parametrize(
    ("amount", "currency", "expected"),
    [
        ("1500", "RUB", "1 500 ₽"),
        ("1500.50", "RUB", "1 500,50 ₽"),
        ("1500.00", "USD", "1 500 $"),
        ("99.9", "EUR", "99,90 €"),
    ],
)
def test_format_money(amount: str, currency: str, expected: str) -> None:
    assert format_money(amount, currency=currency) == expected


def test_format_money_without_currency() -> None:
    assert format_money("1234.56", with_currency=False) == "1 234,56"


def test_max_amount_bound() -> None:
    assert parse_amount(str(MAX_AMOUNT)) is not None
    assert parse_amount(str(MAX_AMOUNT * 10)) is None
