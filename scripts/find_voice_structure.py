"""Найти и показать структуру последнего голосового сообщения.

Читает историю событий с начала (marker=1) и ищет сообщения с вложениями,
печатая полную структуру вложения. Отчёт: ``.report/voice_structure.txt``.

Запуск (бот остановлен)::

    python -m scripts.find_voice_structure
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxAPIError, MaxClient  # noqa: E402
from bot.config import get_settings  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_structure.txt"
JSON_REPORT = PROJECT_ROOT / ".report" / "voice_update.json"


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=30
    ) as client:
        log("Читаю историю событий начиная с marker=32600...")
        try:
            batch = await client.get_updates(marker=32600, timeout=10, limit=100)
        except MaxAPIError as exc:
            log(f"ОШИБКА: {exc}")
            return 1

    updates = batch.get("updates") or []
    log(f"Получено событий: {len(updates)}\n")

    voice_found = 0
    for update in updates:
        update_type = update.get("update_type")
        message = update.get("message") or {}
        body = message.get("body") or {}
        attachments = body.get("attachments") or []
        sender = message.get("sender") or {}
        text = (body.get("text") or "")[:60]

        if not attachments:
            if update_type == "message_created":
                log(f"[{update_type}] user={sender.get('user_id')} text={text!r}")
            continue

        types = [a.get("type") for a in attachments if isinstance(a, dict)]
        log(f"[{update_type}] user={sender.get('user_id')} text={text!r} вложения={types}")

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            payload = attachment.get("payload") or {}
            body_inner = payload.get("body") or {}
            looks_audio = (
                attachment.get("type") in {"audio", "voice"}
                or "voices" in body_inner
                or payload.get("audio_type")
            )
            if not looks_audio:
                continue
            voice_found += 1
            log("\n=== НАЙДЕНО АУДИО ===")
            log(f"  attachment.type = {attachment.get('type')!r}")
            log(f"  payload keys    = {sorted(payload.keys())}")
            log(f"  payload.body    = {json.dumps(body_inner, ensure_ascii=False)[:800]}")
            log("  ПОЛНАЯ СТРУКТУРА ВЛОЖЕНИЯ:")
            log(json.dumps(attachment, ensure_ascii=False, indent=2)[:3000])
            JSON_REPORT.write_text(
                json.dumps(update, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log("\n")

    log(f"Найдено аудио-вложений: {voice_found}")
    if voice_found == 0:
        log("\nАудио не найдено. Показываю структуру последнего сообщения с вложениями:")
        for update in reversed(updates):
            body = (update.get("message") or {}).get("body") or {}
            if body.get("attachments"):
                log(json.dumps(update, ensure_ascii=False, indent=2)[:3000])
                break

    print(out.getvalue()[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
