"""Проверить доступные методы MAX API и историю чата.

``GET /chats`` отдаёт 404 — проверяем альтернативы и структуру сообщений
для известного ``chat_id`` (это ключ к восстановлению голосовых).
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

REPORT = PROJECT_ROOT / ".report" / "voice_diag2.txt"
CHAT_ID = 461841194
USER_ID = 72910765


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
        timeout=httpx.Timeout(40.0), verify=verify_option(), headers=headers
    ) as client:
        log("=== A. Доступные методы (проба) ===")
        probes = [
            ("GET /me", "GET", f"{base}/me", {}),
            ("GET /chats", "GET", f"{base}/chats", {"count": 10}),
            ("GET /dialogs", "GET", f"{base}/dialogs", {"count": 10}),
            ("GET /messages?chat_id", "GET", f"{base}/messages", {"chat_id": CHAT_ID, "count": 10}),
            ("GET /messages?user_id", "GET", f"{base}/messages", {"user_id": USER_ID, "count": 10}),
            ("GET /chats/{id}", "GET", f"{base}/chats/{CHAT_ID}", {}),
        ]
        for label, method, url, params in probes:
            try:
                response = await client.request(method, url, params=params or None)
                log(f"  [{response.status_code}] {label} → {response.text[:180]}")
            except Exception as exc:
                log(f"  [ERR ] {label}: {type(exc).__name__}: {exc}")

        log("\n=== B. История чата (структура сообщений) ===")
        try:
            response = await client.get(
                f"{base}/messages", params={"chat_id": CHAT_ID, "count": 20}
            )
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                payload = response.json()
                log(f"Ключи ответа: {sorted(payload.keys())}")
                messages = payload.get("messages") or []
                log(f"Сообщений: {len(messages)}")
                for message in messages:
                    body = message.get("body") or {}
                    sender = message.get("sender") or {}
                    recipient = message.get("recipient") or {}
                    attachments = body.get("attachments") or []
                    types = [
                        item.get("type") for item in attachments if isinstance(item, dict)
                    ]
                    log(
                        f"  mid={body.get('mid')} seq={body.get('seq')} "
                        f"ts={message.get('timestamp')} "
                        f"sender={sender.get('user_id')}(bot={bool(sender.get('is_bot'))}) "
                        f"chat={recipient.get('chat_id')} text={(body.get('text') or '')[:24]!r} "
                        f"att={types}"
                    )
                    for attachment in attachments:
                        if isinstance(attachment, dict) and attachment.get("type") in {
                            "audio",
                            "voice",
                        }:
                            log("    !!! АУДИО:")
                            log(
                                json.dumps(attachment, ensure_ascii=False, indent=2).replace(
                                    "\n", "\n    "
                                )[:1200]
                            )
            else:
                log(response.text[:300])
        except Exception as exc:
            log(f"ОШИБКА: {type(exc).__name__}: {exc}")

        log("\n=== C. Сырые обновления длинным polling ===")
        try:
            response = await client.get(
                f"{base}/updates", params={"timeout": 8, "limit": 50}
            )
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                payload = response.json()
                updates = payload.get("updates") or []
                log(f"Событий: {len(updates)}, marker={payload.get('marker')}")
                for update in updates:
                    log(
                        f"  type={update.get('update_type')} keys={sorted(update.keys())} "
                        f"has_message={bool(update.get('message'))}"
                    )
        except Exception as exc:
            log(f"ОШИБКА: {type(exc).__name__}: {exc}")

    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
