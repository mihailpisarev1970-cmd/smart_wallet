"""Диагностика голосовых сообщений: что реально отдаёт MAX.

Задача: понять, как восстановить сообщение, если событие ``message_created``
пришло без поля ``message`` (только ``timestamp`` + ``update_type`` +
``user_locale`` — ни ``chat_id``, ни ``user_id``).

Проверяем:
1. ``GET /chats`` — список чатов бота (какие chat_id доступны);
2. ``GET /messages?chat_id=`` — история чата: поля ``mid``, ``seq``,
   ``timestamp``, вложения;
3. ``GET /updates`` с ``marker=-1`` — сырой вид событий.

Отчёт: ``.report/voice_diag.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "voice_diag.txt"
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
        # 1. Чаты бота
        log("=== 1. GET /chats ===")
        chat_ids: list[int] = []
        try:
            response = await client.get(f"{base}/chats", params={"count": 50})
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                chats = response.json().get("chats") or []
                for chat in chats:
                    chat_id = chat.get("chat_id")
                    chat_type = chat.get("type")
                    title = chat.get("title") or (chat.get("dialog_with_user") or {}).get(
                        "first_name", ""
                    )
                    log(f"  chat_id={chat_id} type={chat_type} title={title!r}")
                    if chat_id:
                        chat_ids.append(int(chat_id))
        except Exception as exc:
            log(f"ОШИБКА: {type(exc).__name__}: {exc}")

        # 2. Сообщения каждого чата
        log("\n=== 2. GET /messages?chat_id= ===")
        for chat_id in chat_ids:
            try:
                response = await client.get(
                    f"{base}/messages", params={"chat_id": chat_id, "count": 15}
                )
            except Exception as exc:
                log(f"  chat_id={chat_id}: ОШИБКА {type(exc).__name__}")
                continue
            log(f"\n  -- chat_id={chat_id}: HTTP {response.status_code}")
            if response.status_code >= 400:
                log(f"     {response.text[:200]}")
                continue
            messages = response.json().get("messages") or []
            for message in messages:
                body = message.get("body") or {}
                sender = message.get("sender") or {}
                recipient = message.get("recipient") or {}
                attachments = body.get("attachments") or []
                types = [
                    item.get("type") for item in attachments if isinstance(item, dict)
                ]
                log(
                    f"    mid={body.get('mid')} seq={body.get('seq')} "
                    f"ts={message.get('timestamp')} "
                    f"sender={sender.get('user_id')}(bot={bool(sender.get('is_bot'))}) "
                    f"recipient_chat={recipient.get('chat_id')} "
                    f"text={(body.get('text') or '')[:20]!r} att={types}"
                )
                for attachment in attachments:
                    if isinstance(attachment, dict) and attachment.get("type") in {
                        "audio",
                        "voice",
                    }:
                        log("      ПОЛНАЯ СТРУКТУРА АУДИО:")
                        log(
                            json.dumps(attachment, ensure_ascii=False, indent=2).replace(
                                "\n", "\n      "
                            )[:1500]
                        )

        # 3. Последние события
        log("\n=== 3. GET /updates (marker=-1, сырые события) ===")
        try:
            response = await client.get(
                f"{base}/updates", params={"marker": -1, "timeout": 3, "limit": 100}
            )
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                payload = response.json()
                updates = payload.get("updates") or []
                log(f"Новых событий: {len(updates)}")
                for update in updates:
                    log(
                        f"  type={update.get('update_type')} "
                        f"keys={sorted(update.keys())} "
                        f"has_message={bool(update.get('message'))}"
                    )
                log(f"marker в ответе: {payload.get('marker')}")
        except Exception as exc:
            log(f"ОШИБКА: {type(exc).__name__}: {exc}")

    log(f"\nURL для теста: https://max.ru/{USER_ID}")
    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
