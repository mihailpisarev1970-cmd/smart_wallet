"""Скачать голосовое из MAX по сохранённому URL и определить формат.

Берёт последнее вложение из ``logs/attachments/*.json``, скачивает файл,
определяет реальный формат и пробует STT с разными вариантами.

Отчёт: ``.report/voice_format.txt``.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_format.txt"
ATTACH_DIR = PROJECT_ROOT / "logs" / "attachments"


def detect_format(data: bytes) -> str:
    """Определить контейнер по magic bytes."""
    head = data[:64]
    if head[:4] == b"OggS":
        # Ищем имя кодека внутри Ogg-страницы
        codec = "?"
        if b"OpusHead" in data[:4096]:
            codec = "Opus"
        elif b"\x01vorbis" in data[:4096]:
            codec = "Vorbis"
        elif b"Speex" in data[:4096]:
            codec = "Speex"
        elif b"fLaC" in data[:4096]:
            codec = "FLAC-in-Ogg"
        return f"OGG ({codec})"
    if head[:3] == b"ID3":
        return "MP3 (ID3v2)"
    if head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2", b"\xff\xf1"):
        return "MP3 (frame sync)"
    if head[:4] == b"RIFF":
        return "WAV (RIFF)"
    if head[4:8] == b"ftyp":
        brand = head[8:12].decode("ascii", errors="replace")
        return f"MP4/M4A (brand={brand})"
    if head[:4] == b"\x1aE\xdf\xa3":
        return "WebM/Matroska"
    if head[:3] == b"AMR":
        return "AMR"
    if head[:4] == b"#!AMR":
        return "AMR-NB"
    return f"неизвестен: {head[:16]!r}"


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    files = sorted(ATTACH_DIR.glob("*.json")) if ATTACH_DIR.exists() else []
    if not files:
        log(f"Нет сохранённых вложений в {ATTACH_DIR}")
        log("Отправьте голосовое боту.")
        return 1

    latest = files[-1]
    log(f"Файл вложения: {latest.name}")
    data = json.loads(latest.read_text(encoding="utf-8"))
    payload = data.get("payload") or {}
    url = payload.get("url")
    log(f"URL: {str(url)[:110]}")
    log(f"token: {str(payload.get('token'))[:40]}...")

    if not url:
        log("Нет URL!")
        return 2

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option()
    ) as client:
        log("\n=== 1. Скачивание ===")
        headers = {"Authorization": settings.max_bot_token}
        response = await client.get(url, headers=headers)
        log(f"HTTP {response.status_code}")
        log(f"Content-Type: {response.headers.get('content-type')}")
        log(f"Content-Length: {response.headers.get('content-length')}")
        audio = response.content
        log(f"Размер: {len(audio)} байт")
        log(f"Формат: {detect_format(audio)}")
        log(f"Первые 48 байт (hex): {audio[:48].hex()}")

        sample = PROJECT_ROOT / ".report" / "voice_sample.bin"
        sample.write_bytes(audio)
        log(f"Сохранено: {sample}")

        # 2. STT с разными расширениями и MIME
        log("\n=== 2. STT: gpt-4o-transcribe ===")
        base = settings.stt_api_base_url.rstrip("/")
        stt_headers = {"Authorization": f"Bearer {settings.stt_api_key}"}
        variants = [
            ("voice.ogg", "audio/ogg"),
            ("voice.oga", "audio/ogg"),
            ("voice.ogg", "audio/ogg; codecs=opus"),
            ("voice.opus", "audio/opus"),
            ("voice.mp3", "audio/mpeg"),
            ("voice.m4a", "audio/mp4"),
            ("voice.wav", "audio/wav"),
            ("voice.webm", "audio/webm"),
            ("voice.oga", "application/octet-stream"),
        ]
        for filename, mime in variants:
            try:
                stt = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=stt_headers,
                    data={"model": "gpt-4o-transcribe"},
                    files={"file": (filename, audio, mime)},
                )
                log(f"  {filename:12} {mime:28} → HTTP {stt.status_code} {stt.text[:150]}")
            except Exception as exc:
                log(f"  {filename:12} {mime:28} → ИСКЛЮЧЕНИЕ {type(exc).__name__}")

        # 3. Без language (может быть причина)
        log("\n=== 3. Без параметра language ===")
        for filename, mime in (("voice.ogg", "audio/ogg"), ("voice.mp3", "audio/mpeg")):
            try:
                stt = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=stt_headers,
                    data={"model": "gpt-4o-transcribe"},
                    files={"file": (filename, audio, mime)},
                )
                log(f"  {filename:12} → HTTP {stt.status_code} {stt.text[:150]}")
            except Exception as exc:
                log(f"  {filename:12} → ИСКЛЮЧЕНИЕ {type(exc).__name__}")

    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
