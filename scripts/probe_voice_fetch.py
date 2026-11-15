"""Проверка: как получить сообщение, если в событии нет поля ``message``.

MAX присылает для голосовых ``message_created`` **без** ``message``
(только ``timestamp``). Пробуем восстановить сообщение через API:

* ``GET /messages?chat_id=<id>&count=N`` — список сообщений чата;
* ``GET /messages/{mid}`` — сообщение по id.

Отчёт: ``.report/voice_fetch.txt``, сырые ответы — ``.report/voice_fetch.json``.
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

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_fetch.txt"
RAW = PROJECT_ROOT / ".report" / "voice_fetch.json"
CHAT_ID = 461841194
USER_ID = 72910765


async def main() -> int:
    settings = get_settings()
    base = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    out = io.StringIO()
    raw: dict[str, object] = {}

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(40.0), verify=verify_option(), headers=headers
    ) as client:
        attempts = [
            ("GET /messages?chat_id", f"{base}/messages", {"chat_id": CHAT_ID, "count": 20}),
            ("GET /messages?user_id", f"{base}/messages", {"user_id": USER_ID, "count": 20}),
        ]
        for label, url, params in attempts:
            try:
                response = await client.get(url, params=params)
            except Exception as exc:
                log(f"[ERR ] {label}: {type(exc).__name__}: {exc}")
                continue
            log(f"[{response.status_code}] {label} → {response.text[:400]}")
            if response.status_code < 400:
                raw[label] = response.json()

        # Пробуем получить последние сообщения через /updates с большим лимитом
        # и ищем в них сообщения с аудио (возможно, в истории они полные).
        try:
            response = await client.get(
                f"{base}/updates", params={"marker": 32610, "timeout": 5, "limit": 200}
            )
            if response.status_code < 400:
                payload = response.json()
                updates = payload.get("updates") or []
                raw["updates"] = updates
                log(f"\nGET /updates (marker=32610): событий {len(updates)}")
                for update in updates:
                    if update.get("update_type") != "message_created":
                        continue
                    message = update.get("message")
                    if not message:
                        log(f"  message_created без message: keys={sorted(update.keys())}")
                        continue
                    body = message.get("body") or {}
                    attachments = body.get("attachments") or []
                    if attachments:
                        types = [a.get("type") for a in attachments if isinstance(a, dict)]
                        log(f"  message_created с вложениями: {types}")
                        for attachment in attachments:
                            if isinstance(attachment, dict) and attachment.get("type") in {
                                "audio", "voice"
                            }:
                                log("  СТРУКТУРА АУДИО:")
                                log(json.dumps(attachment, ensure_ascii=False, indent=2)[:2000])
        except Exception as exc:
            log(f"ОШИБКА /updates: {exc}")

    RAW.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out.getvalue()[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
