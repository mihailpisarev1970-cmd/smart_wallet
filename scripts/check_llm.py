"""Проверка подключения к LLM (AI Dostup) на реальном запросе.

Запуск::

    python -m scripts.check_llm                     # простой запрос
    python -m scripts.check_llm --parse "Потратил 1250 на продукты"

Проверяет:
1. доступность ``POST /chat/completions`` с ключом из ``.env``;
2. что модель отвечает;
3. (с ``--parse``) что разбор фразы даёт корректную структурированную операцию.

Отчёт: ``.report/llm.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.constants import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES  # noqa: E402
from bot.services.ai_base import AIError, AINotConfiguredError  # noqa: E402
from bot.services.ai_schema import parse_operations  # noqa: E402
from bot.services.llm_provider import build_provider  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "llm.txt"


async def main(parse_text: str | None) -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    log(f"Base URL: {settings.ai_dostup_base_url}")
    log(f"Модель:   {settings.ai_dostup_model}")
    log(f"Ключ:     {settings.ai_dostup_api_key[:12]}...{settings.ai_dostup_api_key[-6:]}")
    log(f"Настроен: {settings.llm_configured}")

    provider = build_provider(settings)
    started = time.perf_counter()
    try:
        result = await provider.complete(
            [
                {"role": "system", "content": "Отвечай одним словом."},
                {"role": "user", "content": "Скажи: работает"},
            ],
            max_tokens=20,
        )
    except AINotConfiguredError as exc:
        log(f"ОШИБКА конфигурации: {exc}")
        return 2
    except AIError as exc:
        log(f"ОШИБКА запроса: {exc}")
        return 1

    log(f"Ответ модели: {result.content[:200]!r}")
    log(f"Модель в ответе: {result.model}")
    log(f"Токены: {result.prompt_tokens}/{result.completion_tokens}")
    log(f"Задержка: {result.latency_ms} мс (всего {int((time.perf_counter() - started) * 1000)} мс)")

    if parse_text:
        log("")
        log(f"Разбор фразы: {parse_text!r}")
        try:
            parsed = await parse_operations(
                provider,
                parse_text,
                expense_categories=list(DEFAULT_EXPENSE_CATEGORIES),
                income_categories=list(DEFAULT_INCOME_CATEGORIES),
            )
        except (AIError, Exception) as exc:
            log(f"ОШИБКА разбора: {type(exc).__name__}: {exc}")
            return 3
        for index, operation in enumerate(parsed.operations, start=1):
            log(
                f"  #{index}: {operation.type} {operation.amount} {operation.currency} "
                f"«{operation.category}» дата={operation.operation_date} "
                f"комментарий={operation.comment!r}"
            )
        log(f"  confidence={parsed.confidence}")

    log("")
    log("OK: LLM работает")
    print(out.getvalue())
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--parse", type=str, default=None, help="Текст для проверки разбора")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.parse)))
