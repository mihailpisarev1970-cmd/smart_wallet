"""Сравнение запроса из кода бота и «рабочего» запроса.

Показывает точные поля multipart, которые отправляет
:class:`OpenAICompatibleSTT`, и воспроизводит их вручную — чтобы найти
расхождение, из-за которого провайдер отвечает 400.

Запуск::

    python -m scripts.probe_stt_diff
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "stt_diff.txt"
SAMPLE = PROJECT_ROOT / ".report" / "speech_sample.wav"


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    audio = SAMPLE.read_bytes()
    base = settings.stt_api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}

    # 1. Что отправляет сам провайдер-класс бота
    log("=== 1. Запрос через OpenAICompatibleSTT (как в боте) ===")
    from bot.services.stt_provider import OpenAICompatibleSTT

    provider = OpenAICompatibleSTT(settings)
    try:
        text, latency = await provider._transcribe_with(
            "gpt-4o-transcribe", audio, SAMPLE.name, "финансы"
        )
        log(f"  OK: {text!r} ({latency} мс)")
    except Exception as exc:
        log(f"  ОШИБКА: {type(exc).__name__}: {exc}")

    # 2. Ручной запрос через httpx: посмотрим, какие поля реально уходят
    log("\n=== 2. Как httpx формирует multipart ===")
    data = {
        "model": "gpt-4o-transcribe",
        "language": settings.stt_language,
        "response_format": "json",
        "prompt": "Личные финансы",
    }
    files = {"file": (SAMPLE.name, audio, "audio/wav")}
    request = httpx.Request(
        "POST",
        f"{base}/audio/transcriptions",
        headers=headers,
        data=data,
        files=files,
    )
    body = request.read()
    log(f"  Content-Type: {request.headers.get('content-type')}")
    log(f"  Размер тела: {len(body)} байт")
    preview = body[:600].decode("utf-8", errors="replace")
    log(f"  Начало тела:\n{preview[:600]}")

    # 3. Повторный запрос с тем же телом вручную
    log("\n=== 3. Повтор через httpx (то же тело) ===")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option(), headers=headers
    ) as client:
        response = await client.post(
            f"{base}/audio/transcriptions",
            data=data,
            files={"file": (SAMPLE.name, audio, "audio/wav")},
        )
        log(f"  HTTP {response.status_code}: {response.text[:300]}")

    # 4. Проверяем: не мешает ли prompt
    log("\n=== 4. Без prompt ===")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option(), headers=headers
    ) as client:
        response = await client.post(
            f"{base}/audio/transcriptions",
            data={"model": "gpt-4o-transcribe", "language": "ru"},
            files={"file": (SAMPLE.name, audio, "audio/wav")},
        )
        log(f"  HTTP {response.status_code}: {response.text[:300]}")

    # 5. С длинным prompt (как передаёт бот)
    log("\n=== 5. С prompt как в боте ===")
    long_prompt = "Личные финансы: расходы, доходы, суммы в рублях, категории покупок."
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option(), headers=headers
    ) as client:
        response = await client.post(
            f"{base}/audio/transcriptions",
            data={
                "model": "gpt-4o-transcribe",
                "language": "ru",
                "response_format": "json",
                "prompt": long_prompt,
            },
            files={"file": (SAMPLE.name, audio, "audio/wav")},
        )
        log(f"  HTTP {response.status_code}: {response.text[:300]}")

    print(out.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
