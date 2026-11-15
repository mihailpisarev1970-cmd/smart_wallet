"""Работа с денежными суммами.

Требования ТЗ (п. 7.2): денежные значения — ``Decimal``, ``float`` не
используется. Суммы хранятся в БД как ``NUMERIC(14, 2)``.

Модуль умеет разбирать «человеческий» ввод:
``"1500"``, ``"1 500,50"``, ``"1.500,50"``, ``"1200р"``, ``"15к"``, ``"2,5 тыс"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

#: Максимальная сумма одной операции (защита от опечаток и переполнения).
MAX_AMOUNT = Decimal("999999999.99")

#: Множители для «тысяч»: 15к = 15 000.
_MULTIPLIERS: dict[str, Decimal] = {
    "к": Decimal(1000),
    "k": Decimal(1000),
    "тыс": Decimal(1000),
    "тысяч": Decimal(1000),
    "тысячи": Decimal(1000),
    "м": Decimal(1000000),
    "m": Decimal(1000000),
    "млн": Decimal(1000000),
    "млн.": Decimal(1000000),
}

_AMOUNT_RE = re.compile(
    r"(?P<number>"
    r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d{1,2})?"  # 1 234 567,89
    r"|\d{1,3}(?:\.\d{3})+(?:,\d{1,2})?"                 # 1.234.567,89
    r"|\d+(?:[.,]\d{1,2})?"                              # 1234,56
    r")"
    r"\s*(?P<suffix>млн\.?|тысяч[а-я]*|тыс\.?|[кkмm])?",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ParsedAmount:
    """Результат разбора суммы."""

    amount: Decimal
    raw: str

    def __str__(self) -> str:
        return format_money(self.amount, with_currency=False)


def to_decimal(value: Decimal | int | str | float, *, places: str = "0.01") -> Decimal:
    """Привести значение к ``Decimal`` с округлением до копеек.

    ``float`` конвертируется через ``str``, чтобы не тащить двоичную погрешность.
    """
    if isinstance(value, float):
        value = str(value)
    try:
        result = Decimal(value) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Некорректная сумма: {value!r}") from exc
    return result.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def format_money(
    amount: Decimal | int | str,
    *,
    currency: str = "RUB",
    with_currency: bool = True,
) -> str:
    """Отформатировать сумму по-русски: ``1 500,50 ₽``.

    Нули копеек отбрасываются только если сумма целая (``1 500``),
    иначе сохраняются два знака (``99,90``).
    """
    value = to_decimal(amount)
    text = f"{value:,.2f}".replace(",", " ")
    if text.endswith(".00"):
        text = text[:-3]
    text = text.replace(".", ",")
    if not with_currency:
        return text
    symbol = {"RUB": "₽", "USD": "$", "EUR": "€"}.get(currency, currency)
    return f"{text} {symbol}"


def parse_amount(text: str | None) -> ParsedAmount | None:
    """Разобрать сумму из пользовательского текста.

    Возвращает ``None``, если число не найдено или оно некорректно.

    Примеры::

        >>> parse_amount("1 500,50").amount
        Decimal('1500.50')
        >>> parse_amount("15к").amount
        Decimal('15000.00')
        >>> parse_amount("без числа") is None
        True
    """
    if not text or not isinstance(text, str):
        return None
    cleaned = text.replace("\u00a0", " ").replace("\u202f", " ").strip()

    match = _AMOUNT_RE.search(cleaned)
    if not match:
        return None

    # Отрицательная сумма: знак перед числом («-100», «−100», «минус 100»).
    prefix = cleaned[: match.start("number")].rstrip()
    if prefix.endswith(("-", "−", "–")):
        return None

    number_raw = match.group("number").replace(" ", "")
    suffix = (match.group("suffix") or "").lower().rstrip(".")

    # Определяем десятичный разделитель: «1.500,50» -> 1500.50
    has_comma, has_dot = "," in number_raw, "." in number_raw
    if has_comma and has_dot:
        number_raw = number_raw.replace(".", "").replace(",", ".")
    else:
        number_raw = number_raw.replace(",", ".")

    try:
        value = Decimal(number_raw)
    except InvalidOperation:
        return None

    multiplier = _MULTIPLIERS.get(suffix)
    if multiplier:
        value *= multiplier

    if value <= 0 or value > MAX_AMOUNT:
        return None
    return ParsedAmount(amount=to_decimal(value), raw=match.group(0).strip())
