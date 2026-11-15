"""Проверка, проксирует ли AI Dostup распознавание речи (ТЗ п. 4.4).

В ТЗ сказано: если AI Dostup предоставляет эндпоинт
``/v1/audio/transcriptions``, STT можно направить через него с тем же
``AI_DOSTUP_API_KEY`` — отдельный ключ тогда не нужен.

Скрипт пробует несколько вариантов и пишет результат в ``.report/stt_probe.txt``:

1. ``GET {base}/models`` — есть ли в каталоге whisper-модели;
2. ``POST {base}/audio/transcriptions`` с моделью ``whisper-1``;
3. ``POST`` с моделью ``gpt-4o-transcribe``.

Для запроса генерируется короткий валидный WAV (тишина): важен не текст,
а код ответа — 200 означает «эндпоинт работает и ключ принят».
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "stt_probe.txt"


def make_wav(seconds: float = 1.0, framerate: int = 16000) -> bytes:
    """Сгенерировать корректный WAV (тихий тон) для тестового запроса."""
    frames = int(seconds * framerate)
    samples = b"".join(
        struct.pack("<h", int(300 * math.sin(2 * math.pi * 440 * i / framerate)))
        for i in range(frames)
    )
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, framerate, framerate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(samples))
    return header + samples


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.ai_dostup_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.ai_dostup_api_key}"}
    log(f"Проверяем AI Dostup как STT-провайдер: {base}")
    log(f"Ключ: {settings.ai_dostup_api_key[:12]}...\n")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0), verify=verify_option(), headers=headers
    ) as client:
        # 1. Каталог моделей
        try:
            response = await client.get(f"{base}/models")
            log(f"GET /models: HTTP {response.status_code}")
            if response.status_code < 400:
                payload = response.json()
                models = [
                    str(item.get("id"))
                    for item in (payload.get("data") or payload.get("models") or [])
                    if isinstance(item, dict)
                ]
                whisper = [m for m in models if "whisper" in m.lower() or "transcribe" in m.lower()]
                log(f"  Моделей всего: {len(models)}")
                log(f"  STT-модели в каталоге: {whisper or 'нет'}")
                log(f"  Первые модели: {models[:10]}")
        except Exception as exc:
            log(f"GET /models: ошибка {type(exc).__name__}: {exc}")

        # 2-3. Пробуем распознавание
        wav = make_wav()
        working: list[str] = []
        for model in ("whisper-1", "gpt-4o-transcribe"):
            try:
                response = await client.post(
                    f"{base}/audio/transcriptions",
                    data={"model": model, "language": "ru", "response_format": "json"},
                    files={"file": ("probe.wav", wav, "audio/wav")},
                )
            except Exception as exc:
                log(f"POST /audio/transcriptions ({model}): ошибка {type(exc).__name__}: {exc}")
                continue
            log(f"POST /audio/transcriptions ({model}): HTTP {response.status_code}")
            log(f"  Ответ: {response.text[:300]}")
            if response.status_code < 400:
                working.append(model)

    log("")
    if working:
        log(f"РЕЗУЛЬТАТ: AI Dostup ПОДДЕРЖИВАЕТ STT (модели: {', '.join(working)}).")
        log("Отдельный ключ не нужен — можно использовать AI_DOSTUP_API_KEY:")
        log(f"  STT_API_BASE_URL={base}")
        log("  STT_API_KEY=<тот же ключ AI Dostup>")
        return 0

    log("РЕЗУЛЬТАТ: AI Dostup НЕ предоставляет /audio/transcriptions.")
    log("Нужен отдельный STT-провайдер (ключ OpenAI или совместимого прокси).")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
