"""Проверить, как параметры запроса влияют на скорость deepseek-v4.1-flash.

Гипотеза: ``max_tokens=800`` и ``response_format`` замедляют ответ.
Модель оставляем ту же (требование заказчика) — оптимизируем запрос.

Отчёт: ``.report/llm_tuning.txt``.
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.services.ai_schema import SYSTEM_PROMPT, sanitize_user_text  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "llm_tuning.txt"
MODEL = "deepseek-v4.1-flash-1017"
PHRASE = "Потратил 350 рублей на кофе"

EXPENSES = "Продукты, Рестораны и кафе, Транспорт, Автомобиль, Жильё, Коммунальные платежи, Покупки, Здоровье, Развлечения, Образование, Путешествия, Подписки, Другое"
INCOMES = "Зарплата, Подработка, Бизнес, Инвестиции, Подарки, Другие доходы"


async def measure(
    client: httpx.AsyncClient,
    base: str,
    headers: dict[str, str],
    label: str,
    payload_extra: dict,
    runs: int = 3,
) -> float:
    """Замерить среднее время ответа."""
    from datetime import date

    system = SYSTEM_PROMPT.format(
        today=date.today().isoformat(),
        expense_categories=EXPENSES,
        income_categories=INCOMES,
    )
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"<<<СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ>>>\n{sanitize_user_text(PHRASE)}"},
        ],
        **payload_extra,
    }

    times: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        response = await client.post(f"{base}/chat/completions", headers=headers, json=body)
        elapsed = time.perf_counter() - started
        if response.status_code >= 400:
            return -1.0
        times.append(elapsed)

    average = sum(times) / len(times)
    return average


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.ai_dostup_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.ai_dostup_api_key}"}

    from datetime import date

    system_prompt = SYSTEM_PROMPT.format(
        today=date.today().isoformat(),
        expense_categories=EXPENSES,
        income_categories=INCOMES,
    )
    log(f"Модель: {MODEL}")
    log(f"Фраза: {PHRASE}")
    log(f"Промпт: {len(system_prompt)} символов (~{len(system_prompt) // 4} токенов)\n")

    variants = [
        ("A max_tokens=800 + json_object (текущий)", {"temperature": 0.0, "max_tokens": 800, "response_format": {"type": "json_object"}}),
        ("B max_tokens=150 без response_format", {"temperature": 0.0, "max_tokens": 150}),
        ("C max_tokens=800 без response_format", {"temperature": 0.0, "max_tokens": 800}),
        ("D max_tokens=150 + json_object", {"temperature": 0.0, "max_tokens": 150, "response_format": {"type": "json_object"}}),
        ("E max_tokens=150 без response_format (повтор)", {"temperature": 0.0, "max_tokens": 150}),
    ]

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), verify=verify_option()) as client:
        for label, extra in variants:
            times: list[float] = []
            for _ in range(5):
                started = time.perf_counter()
                response = await client.post(
                    f"{base}/chat/completions",
                    headers=headers,
                    json={
                        "model": MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {
                                "role": "user",
                                "content": f"<<<СООБЩЕНИЕ ПОЛЬЗОВАТЕЛЯ>>>\n{sanitize_user_text(PHRASE)}",
                            },
                        ],
                        **extra,
                    },
                )
                elapsed = time.perf_counter() - started
                if response.status_code >= 400:
                    times = []
                    break
                times.append(elapsed)
            if not times:
                log(f"  {label:45} → ОШИБКА")
                continue
            times.sort()
            log(
                f"  {label:45} → мин {times[0]:5.2f}  медиана {times[len(times) // 2]:5.2f}  "
                f"ср {sum(times) / len(times):5.2f}"
            )

    print(out.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
