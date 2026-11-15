"""Проверить доступные STT-модели у AI Dostup и причину HTTP 400.

Ключевой вопрос: почему ``gpt-4o-transcribe`` возвращает 400.
Проверяем:
1. список моделей ``GET /models``;
2. распознавание сгенерированного WAV (гарантированно валидный формат);
3. те же запросы с ``whisper-1``.

Отчёт: ``.report/stt_models.txt``.
"""

from __future__ import annotations

import asyncio
import io
import struct
import sys
import wave
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "stt_models.txt"


def make_wav(seconds: float = 2.0, freq: int = 440) -> bytes:
    """Сгенерировать простой WAV (тон) — валидный файл для проверки API."""
    import math

    rate = 16000
    frames = int(rate * seconds)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        samples = b"".join(
            struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(frames)
        )
        wav.writeframes(samples)
    return buffer.getvalue()


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.stt_api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}

    log("=== Настройки ===")
    log(f"base_url: {base}")
    log(f"primary:  {settings.stt_primary_model}")
    log(f"fallback: {settings.stt_fallback_model}")
    log()

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0), verify=verify_option()) as client:
        log("=== 1. GET /models ===")
        try:
            response = await client.get(f"{base}/models", headers=headers)
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                data = response.json().get("data") or []
                ids = sorted(str(item.get("id")) for item in data if isinstance(item, dict))
                log(f"Всего моделей: {len(ids)}")
                log("\nSTT-подобные модели:")
                found = False
                for model_id in ids:
                    low = model_id.lower()
                    if any(k in low for k in ("whisper", "transcribe", "audio", "speech", "tts")):
                        log(f"  ★ {model_id}")
                        found = True
                if not found:
                    log("  (не найдено — провайдер не отдаёт их в /models)")
                log(f"\nПервые 30 моделей: {ids[:30]}")
            else:
                log(response.text[:400])
        except Exception as exc:
            log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

        log("\n=== 2. Распознавание WAV (чистый формат) ===")
        wav = make_wav()
        log(f"WAV размер: {len(wav)} байт")

        for model in ("gpt-4o-transcribe", "whisper-1"):
            log(f"\n--- модель: {model} ---")
            try:
                response = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=headers,
                    data={"model": model, "language": "ru"},
                    files={"file": ("test.wav", wav, "audio/wav")},
                )
                log(f"HTTP {response.status_code}")
                log(response.text[:500])
            except Exception as exc:
                log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

        log("\n=== 3. Без параметра language ===")
        for model in ("gpt-4o-transcribe", "whisper-1"):
            log(f"\n--- модель: {model} ---")
            try:
                response = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=headers,
                    data={"model": model},
                    files={"file": ("test.wav", wav, "audio/wav")},
                )
                log(f"HTTP {response.status_code}")
                log(response.text[:400])
            except Exception as exc:
                log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

    print(out.getvalue()[:7000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
