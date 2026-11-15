"""Точная диагностика: какие параметры `/audio/transcriptions` ломают запрос.

Перебирает комбинации (поле файла, наличие language, response_format,
Content-Type) и показывает, какая именно работает. ТЗ п. 4.4 требует
эмпирической проверки провайдера — это и есть проверка.

Запуск::

    python -m scripts.probe_stt_params

Отчёт: ``.report/stt_params.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "stt_params.txt"
SAMPLE = PROJECT_ROOT / ".report" / "speech_sample.wav"


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    if not SAMPLE.exists():
        log(f"Нет файла {SAMPLE}. Сначала: python -m scripts.check_voices")
        return 1

    audio = SAMPLE.read_bytes()
    log(f"Файл: {SAMPLE.name}, {len(audio)} байт")
    base = settings.stt_api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}

    # Варианты запроса: (описание, поле файла, data, mime)
    variants: list[tuple[str, str, dict[str, str], str]] = [
        ("как в коде", "file", {"model": "gpt-4o-transcribe", "language": "ru", "response_format": "json"}, "audio/wav"),
        ("без response_format", "file", {"model": "gpt-4o-transcribe", "language": "ru"}, "audio/wav"),
        ("без language", "file", {"model": "gpt-4o-transcribe"}, "audio/wav"),
        ("поле data", "data", {"model": "gpt-4o-transcribe"}, "audio/wav"),
        ("поле audio", "audio", {"model": "gpt-4o-transcribe"}, "audio/wav"),
        ("только model", "file", {"model": "gpt-4o-transcribe"}, "application/octet-stream"),
        ("mime audio/mpeg", "file", {"model": "gpt-4o-transcribe"}, "audio/mpeg"),
        ("multipart без model", "file", {}, "audio/wav"),
    ]

    working: list[str] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option(), headers=headers
    ) as client:
        for label, field, data, mime in variants:
            try:
                response = await client.post(
                    f"{base}/audio/transcriptions",
                    data=data,
                    files={field: ("sample.wav", audio, mime)},
                )
            except Exception as exc:
                log(f"[ERR ] {label}: {type(exc).__name__}: {exc}")
                continue
            mark = "OK  " if response.status_code < 400 else "FAIL"
            body = response.text[:180]
            log(f"[{mark}] {label}: HTTP {response.status_code} {body}")
            if response.status_code < 400:
                working.append(label)

    log("")
    if working:
        log(f"РАБОТАЮТ варианты: {working}")
        log("Вывод: провайдер принимает запрос — нужно подстроить параметры в коде.")
    else:
        log("Ни один вариант не прошёл: провайдер отклоняет WAV с речью.")
        log("Проверим на другом формате (MP3/OGG) отдельным скриптом.")
    print(out.getvalue())
    return 0 if working else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
