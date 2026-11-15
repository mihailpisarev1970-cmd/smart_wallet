"""Поймать голосовое из MAX через вебхук и проверить форматы для STT.

Ждём событие с вложением ``audio``, скачиваем файл, определяем формат
и пробуем разные варианты отправки в STT.

Запуск (webhook-сервер должен быть остановлен — порт 8080 свободен)::

    python -m scripts.capture_voice
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import httpx
from aiohttp import web

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "capture_voice.txt"
PORT = 8090


def detect_format(data: bytes) -> str:
    """Определить формат по сигнатуре."""
    if data[:4] == b"OggS":
        return "OGG (OggS)"
    if data[:3] == b"ID3":
        return "MP3 (ID3)"
    if data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "MP3 (frame sync)"
    if data[:4] == b"RIFF":
        return "WAV (RIFF)"
    if data[4:8] == b"ftyp":
        return "MP4/M4A (ftyp)"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "WebM/Matroska"
    return f"неизвестен ({data[:8]!r})"


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()
    captured: asyncio.Queue = asyncio.Queue()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async def handle(request: web.Request) -> web.Response:
        payload = await request.json()
        update_type = payload.get("update_type")
        message = payload.get("message") or {}
        body = message.get("body") or {}
        attachments = body.get("attachments") or []
        types = [item.get("type") for item in attachments if isinstance(item, dict)]
        log(f"СОБЫТИЕ: {update_type}, вложения={types}")
        for item in attachments:
            if isinstance(item, dict) and item.get("type") == "audio":
                await captured.put(item)
        return web.json_response({"ok": True})

    app = web.Application()
    app.router.add_post("/capture", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    log(f"Слушаю http://0.0.0.0:{PORT}")

    try:
        log("Жду голосовое (отправьте боту)... таймаут 180 сек")
        try:
            attachment = await asyncio.wait_for(captured.get(), timeout=180)
        except TimeoutError:
            log("Таймаут — голосовое не пришло")
            return 1

        log("\n=== Вложение из MAX ===")
        log(json.dumps(attachment, ensure_ascii=False, indent=2)[:1500])

        payload_data = attachment.get("payload") or {}
        url = payload_data.get("url")
        if not url:
            log("НЕТ URL во вложении!")
            return 2

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60.0), verify=verify_option()
        ) as client:
            log(f"\n=== Скачивание ===\nURL: {url[:100]}")
            response = await client.get(
                url, headers={"Authorization": settings.max_bot_token}
            )
            log(f"HTTP {response.status_code}")
            log(f"Content-Type: {response.headers.get('content-type')}")
            audio = response.content
            log(f"Размер: {len(audio)} байт")
            log(f"Формат: {detect_format(audio)}")
            log(f"Первые 32 байта (hex): {audio[:32].hex()}")
            log(f"Как текст: {audio[:32]!r}")

            sample = PROJECT_ROOT / ".report" / "voice_from_max.bin"
            sample.write_bytes(audio)
            log(f"Сохранено: {sample}")

            # Сохраним также структуру целиком
            (PROJECT_ROOT / ".report" / "voice_attachment.json").write_text(
                json.dumps(
                    {"attachment": attachment,
                     "content_type": response.headers.get("content-type"),
                     "size": len(audio),
                     "format": detect_format(audio)},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            # Проверяем STT с разными расширениями
            log("\n=== STT-попытки (gpt-4o-transcribe) ===")
            base = settings.stt_api_base_url.rstrip("/")
            headers = {"Authorization": f"Bearer {settings.stt_api_key}"}
            for filename, mime in (
                ("voice.ogg", "audio/ogg"),
                ("voice.oga", "audio/ogg"),
                ("voice.opus", "audio/ogg"),
                ("voice.mp3", "audio/mpeg"),
                ("voice.m4a", "audio/mp4"),
                ("voice.wav", "audio/wav"),
                ("voice.webm", "audio/webm"),
            ):
                try:
                    stt = await client.post(
                        f"{base}/audio/transcriptions",
                        headers=headers,
                        data={"model": "gpt-4o-transcribe"},
                        files={"file": (filename, audio, mime)},
                    )
                    text = stt.text[:200]
                    log(f"  {filename:12} ({mime:12}) → HTTP {stt.status_code} {text}")
                except Exception as exc:
                    log(f"  {filename:12} → ИСКЛЮЧЕНИЕ {type(exc).__name__}")
    finally:
        await runner.cleanup()

    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
