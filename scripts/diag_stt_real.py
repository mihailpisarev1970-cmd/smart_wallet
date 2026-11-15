"""Диагностика STT на реальном голосовом из MAX.

Скачивает последнее голосовое сообщение из чата и пробует распознать его
разными способами, показывая полный ответ API. Нужно, чтобы понять, почему
``gpt-4o-transcribe`` возвращает HTTP 400.

Отчёт: ``.report/stt_diag.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "stt_diag.txt"
CHAT_ID = 461841194


async def main() -> int:
    settings = reload_settings()
    base = settings.max_api_base_url.rstrip("/")
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    headers = {"Authorization": settings.max_bot_token}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0), verify=verify_option()
    ) as client:
        # 1. Найти последнее голосовое в чате
        log("=== 1. Ищу голосовое в чате ===")
        response = await client.get(
            f"{base}/messages", params={"chat_id": CHAT_ID, "count": 20}, headers=headers
        )
        if response.status_code >= 400:
            log(f"ОШИБКА: HTTP {response.status_code} {response.text[:200]}")
            return 1

        audio_url = None
        audio_attachment = None
        for message in response.json().get("messages") or []:
            body = message.get("body") or {}
            sender = message.get("sender") or {}
            if sender.get("is_bot"):
                continue
            for attachment in body.get("attachments") or []:
                if isinstance(attachment, dict) and attachment.get("type") == "audio":
                    audio_attachment = attachment
                    audio_url = (attachment.get("payload") or {}).get("url")
                    break
            if audio_url:
                break

        if not audio_url:
            log("Голосовых в последних 20 сообщениях нет.")
            log("Отправьте голосовое боту и запустите снова.")
            print(out.getvalue())
            return 2

        log("Найдено голосовое:")
        log(json.dumps(audio_attachment, ensure_ascii=False, indent=2)[:1200])
        log(f"\nURL: {audio_url[:120]}")

        # 2. Скачать файл
        log("\n=== 2. Скачиваю файл ===")
        download = await client.get(audio_url, headers=headers)
        log(f"HTTP {download.status_code}, Content-Type: {download.headers.get('content-type')}")
        log(f"Размер: {len(download.content)} байт")
        if download.status_code >= 400:
            log(download.text[:300])
            print(out.getvalue())
            return 3

        audio = download.content
        log(f"Первые байты: {audio[:16]!r}")
        # Определяем формат по magic bytes
        if audio[:4] == b"OggS":
            log("Формат: OGG (по сигнатуре OggS)")
        elif audio[:3] == b"ID3" or audio[:2] == b"\xff\xfb":
            log("Формат: MP3")
        elif audio[:4] == b"RIFF":
            log("Формат: WAV")
        elif audio[4:8] == b"ftyp":
            log("Формат: MP4/M4A")
        else:
            log("Формат: неизвестен")

        path = PROJECT_ROOT / ".report" / "voice_sample.ogg"
        path.write_bytes(audio)
        log(f"Сохранено: {path}")

        # 3. Пробуем распознать разными способами
        log("\n=== 3. Пробую STT ===")
        log(f"STT base URL: {settings.stt_api_base_url}")
        log(f"STT ключ задан: {bool(settings.stt_api_key)}")
        log(f"Основная модель: {settings.stt_primary_model}")

        stt_headers = {"Authorization": f"Bearer {settings.stt_api_key}"}

        attempts = [
            ("gpt-4o-transcribe + ogg", "gpt-4o-transcribe", "voice.ogg", "audio/ogg"),
            ("gpt-4o-transcribe + m4a", "gpt-4o-transcribe", "voice.m4a", "audio/mp4"),
            ("gpt-4o-transcribe + mp3", "gpt-4o-transcribe", "voice.mp3", "audio/mpeg"),
            ("whisper-1 + ogg", "whisper-1", "voice.ogg", "audio/ogg"),
        ]
        for label, model, filename, mime in attempts:
            log(f"\n--- {label} ---")
            try:
                response = await client.post(
                    f"{settings.stt_api_base_url.rstrip('/')}/audio/transcriptions",
                    headers=stt_headers,
                    data={"model": model},
                    files={"file": (filename, audio, mime)},
                )
                log(f"HTTP {response.status_code}")
                body = response.text
                log(body[:600])
            except Exception as exc:
                log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

        # 4. Проверяем доступные модели
        log("\n=== 4. Какие модели доступны у провайдера ===")
        try:
            response = await client.get(
                f"{settings.stt_api_base_url.rstrip('/')}/models", headers=stt_headers
            )
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                data = response.json().get("data") or []
                ids = sorted(item.get("id", "") for item in data if isinstance(item, dict))
                log(f"Моделей: {len(ids)}")
                for model_id in ids:
                    if "whisper" in model_id or "transcribe" in model_id or "audio" in model_id:
                        log(f"  ★ {model_id}")
            else:
                log(response.text[:300])
        except Exception as exc:
            log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

    print(out.getvalue()[:7000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
