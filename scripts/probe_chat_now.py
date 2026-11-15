"""Проверить содержимое чата прямо сейчас (ищем голосовое 12:12).

Смотрит ``GET /messages`` для чата и печатает всё, что есть, включая
вложения и транскрипции. Отчёт: ``.report/chat_now.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "chat_now.txt"
CHAT_ID = 461841194


async def main() -> int:
    settings = get_settings()
    base = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0), verify=verify_option(), headers=headers
    ) as client:
        for count in (10, 30):
            response = await client.get(
                f"{base}/messages", params={"chat_id": CHAT_ID, "count": count}
            )
            log(f"=== GET /messages count={count} → HTTP {response.status_code} ===")
            if response.status_code >= 400:
                log(response.text[:200])
                continue
            messages = response.json().get("messages") or []
            log(f"Сообщений: {len(messages)}")
            for message in messages:
                body = message.get("body") or {}
                sender = message.get("sender") or {}
                attachments = body.get("attachments") or []
                types = [a.get("type") for a in attachments if isinstance(a, dict)]
                log(
                    f"  ts={message.get('timestamp')} "
                    f"mid={body.get('mid')} "
                    f"sender={sender.get('user_id')}(bot={bool(sender.get('is_bot'))}) "
                    f"text={(body.get('text') or '')[:30]!r} att={types}"
                )
                for attachment in attachments:
                    if isinstance(attachment, dict) and attachment.get("type") in {
                        "audio",
                        "voice",
                        "file",
                        "video",
                    }:
                        log("    ВЛОЖЕНИЕ:")
                        log(
                            json.dumps(attachment, ensure_ascii=False, indent=2).replace(
                                "\n", "\n    "
                            )[:900]
                        )
            log()

        # Смотрим также, не осталось ли в очереди /updates событий
        response = await client.get(f"{base}/updates", params={"timeout": 3, "limit": 50})
        log(f"=== GET /updates → HTTP {response.status_code} ===")
        if response.status_code < 400:
            payload = response.json()
            updates = payload.get("updates") or []
            log(f"Событий: {len(updates)}, marker={payload.get('marker')}")
            for update in updates:
                log(
                    f"  type={update.get('update_type')} keys={sorted(update.keys())} "
                    f"ts={update.get('timestamp')}"
                )

    print(out.getvalue()[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
