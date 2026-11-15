"""Пакетная проверка AI-разбора на наборе реальных фраз.

Запуск::

    python -m scripts.check_llm_cases

Проверяет 10 типичных фраз (мультиоперации, даты, доходы, «1,5к»).
Отчёт: ``.report/llm_cases.txt``.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.constants import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES  # noqa: E402
from bot.services.ai_base import AIError  # noqa: E402
from bot.services.ai_schema import parse_operations  # noqa: E402
from bot.services.llm_provider import build_provider  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "llm_cases.txt"

CASES = (
    "Потратил 1250 на продукты",
    "Кофе 320",
    "Зарплата 85000",
    "Такси 450 вчера",
    "Купил кроссовки за 1,5к",
    "Потратил 2000 на бензин и 500 на мойку",
    "Аренда 45000 и коммуналка 6000",
    "Премия 20000 пришла сегодня",
    "Обед 890,50 в кафе",
    "Отдал 3 тыс за ремонт телефона",
)


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    provider = build_provider(settings)
    ok = 0
    for index, phrase in enumerate(CASES, start=1):
        log(f'\n[{index}/{len(CASES)}] "{phrase}"')
        try:
            parsed = await parse_operations(
                provider,
                phrase,
                expense_categories=list(DEFAULT_EXPENSE_CATEGORIES),
                income_categories=list(DEFAULT_INCOME_CATEGORIES),
            )
        except AIError as exc:
            log(f"  ОШИБКА: {exc}")
            continue
        except Exception as exc:
            log(f"  ОШИБКА {type(exc).__name__}: {exc}")
            continue

        for operation in parsed.operations:
            log(
                f"  {operation.type:7} {operation.amount!s:>10} {operation.currency} "
                f"| {operation.category:20} | {operation.operation_date} "
                f"| {operation.comment!r}"
            )
        log(f"  confidence={parsed.confidence:.2f}")
        ok += 1

    log(f"\nУспешно разобрано: {ok}/{len(CASES)}")
    print(out.getvalue())
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
