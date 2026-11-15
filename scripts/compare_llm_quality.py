"""Проверить качество быстрой модели на наборе фраз.

Сравниваем ``gemini-3.7-flash`` (2.2 с) с текущей ``deepseek-v4.1-flash``
(8.5 с) по точности разбора и скорости. Нужно убедиться, что ускорение
не ломает качество.

Отчёт: ``.report/llm_quality.txt``.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
import time
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "llm_quality.txt"

SYSTEM = (
    "Ты разбираешь финансовые операции из русской речи. "
    "Верни ТОЛЬКО валидный JSON без markdown-обёрток:\n"
    '{"operations":[{"type":"expense|income","amount":123.45,'
    '"category":"название","comment":"краткий комментарий"}]}\n'
    "Если операций несколько — верни несколько элементов массива. "
    "Если суммы нет — верни пустой массив."
)

PHRASES = [
    "Потратил 350 рублей на кофе",
    "Купил продукты на 1250",
    "Зарплата 85000 пришла",
    "Заплатил за такси 450 рублей",
    "Потратил 1250 на продукты и 300 на бензин",
    "Получил 5000 подработка",
    "Оплатил коммуналку 6800",
    "Купил кроссовки за 12 тысяч",
    "Перевёл маме 3000",
    "Аптека 780 рублей",
]

MODELS = ["deepseek-v4.1-flash-1017", "gemini-3.7-flash"]


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.ai_dostup_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.ai_dostup_api_key}"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0), verify=verify_option()) as client:
        summary: list[tuple[str, float, int, int]] = []

        for model in MODELS:
            log(f"\n{'=' * 60}\nМОДЕЛЬ: {model}\n{'=' * 60}")
            total_time = 0.0
            valid_json = 0
            correct_count = 0

            for phrase in PHRASES:
                started = time.perf_counter()
                try:
                    response = await client.post(
                        f"{base}/chat/completions",
                        headers=headers,
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": SYSTEM},
                                {"role": "user", "content": phrase},
                            ],
                            "temperature": 0.0,
                            "max_tokens": 300,
                        },
                    )
                    elapsed = time.perf_counter() - started
                    total_time += elapsed
                    content = (
                        (response.json().get("choices") or [{}])[0]
                        .get("message", {})
                        .get("content", "")
                        .strip()
                    )
                    # Убираем возможные ```json обёртки
                    if content.startswith("```"):
                        content = content.split("```")[1]
                        if content.startswith("json"):
                            content = content[4:]
                        content = content.strip()

                    try:
                        payload = json.loads(content)
                        valid_json += 1
                        operations = payload.get("operations") or []
                        correct_count += len(operations)
                        brief = [
                            (op.get("type"), op.get("amount"), op.get("category"))
                            for op in operations
                        ]
                        log(f"  {elapsed:5.2f}с  {phrase[:38]:40} → {brief}")
                    except json.JSONDecodeError:
                        log(f"  {elapsed:5.2f}с  {phrase[:38]:40} → НЕ JSON: {content[:60]}")

                except Exception as exc:
                    log(f"  ОШИБКА: {type(exc).__name__} на {phrase[:30]}")

            avg = total_time / len(PHRASES)
            summary.append((model, avg, valid_json, correct_count))

    log(f"\n{'=' * 60}\nИТОГ\n{'=' * 60}")
    for model, avg, valid_json, correct_count in summary:
        log(
            f"  {model:30} ср. {avg:5.2f}с  JSON {valid_json}/{len(PHRASES)}  "
            f"операций {correct_count}"
        )

    print(out.getvalue()[:7000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
