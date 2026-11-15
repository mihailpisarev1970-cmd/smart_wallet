"""Сравнить скорость LLM-моделей на задаче разбора текста.

Цель: сократить время ответа. Сейчас ``deepseek-v4.1-flash-1017`` тратит
~10 секунд на одну операцию. Проверяем альтернативы из списка AI Dostup.

Отчёт: ``.report/llm_speed.txt``.
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
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "llm_speed.txt"

QUESTION = "Потратил 350 рублей на кофе"

SYSTEM = (
    "Разбери финансовую операцию. Ответь ТОЛЬКО JSON без пояснений:\n"
    '{"operations":[{"type":"expense","amount":0,"category":"","comment":""}]}'
)

MODELS = [
    "deepseek-v4.1-flash-1017",
    "deepseek-v4-flash-0731",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "glm-5-turbo",
    "glm-5.3-flash",
    "gpt-5.6-luna",
]


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.ai_dostup_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.ai_dostup_api_key}"}
    log(f"Запрос: {QUESTION!r}")
    log(f"Base: {base}\n")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), verify=verify_option()) as client:
        results: list[tuple[str, float, str]] = []

        for model in MODELS:
            log(f"--- {model} ---")
            started = time.perf_counter()
            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers=headers,
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": SYSTEM},
                            {"role": "user", "content": QUESTION},
                        ],
                        "temperature": 0.0,
                        "max_tokens": 200,
                    },
                )
                elapsed = time.perf_counter() - started
                if response.status_code >= 400:
                    log(f"  HTTP {response.status_code}: {response.text[:150]}")
                    continue
                payload = response.json()
                content = (
                    (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
                )
                log(f"  {elapsed:.2f} с")
                log(f"  {content[:180]}")
                results.append((model, elapsed, content))
            except Exception as exc:
                log(f"  ИСКЛЮЧЕНИЕ: {type(exc).__name__}")

        log("\n=== ИТОГ (по возрастанию времени) ===")
        for model, elapsed, _content in sorted(results, key=lambda item: item[1]):
            log(f"  {elapsed:6.2f} с  {model}")

    print(out.getvalue()[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
