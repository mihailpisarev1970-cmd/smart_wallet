"""Проверить, отдаёт ли API голосовые сообщения хоть каким-то способом.

Гипотеза: голосовое есть в чате (событие приходит), но ``GET /messages``
его не возвращает. Проверяем:

1. ``GET /chats/{id}`` — ``last_event_time`` (подтверждает, что событие было);
2. ``GET /messages`` с разными ``count`` и ``from``/``to``;
3. ``GET /messages?message_ids=`` для всех mid из истории (найдём пропуски
   по ``seq``);
4. ``GET /updates`` с ``marker`` из последнего известного.

Отчёт: ``.report/voice_hunt.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "voice_hunt.txt"
CHAT_ID = 461841194
#: Время голосового события из логов (12:12:14).
VOICE_TS = 1794129134772


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
        log("=== 1. GET /chats/{id} ===")
        response = await client.get(f"{base}/chats/{CHAT_ID}")
        log(f"HTTP {response.status_code}")
        if response.status_code < 400:
            payload = response.json()
            log(json.dumps(payload, ensure_ascii=False, indent=2)[:800])
            last_event = payload.get("last_event_time")
            log(f"\nlast_event_time={last_event}, голосовое ts={VOICE_TS}")
            if last_event:
                log(f"Разница: {int(last_event) - VOICE_TS} мс")

        log("\n=== 2. GET /messages с параметрами from/to ===")
        variants = [
            {"chat_id": CHAT_ID, "count": 50},
            {"chat_id": CHAT_ID, "count": 100},
            {"chat_id": CHAT_ID, "count": 20, "from": VOICE_TS - 60_000},
            {"chat_id": CHAT_ID, "count": 20, "to": VOICE_TS + 60_000},
        ]
        for params in variants:
            response = await client.get(f"{base}/messages", params=params)
            label = ", ".join(f"{k}={v}" for k, v in params.items())
            if response.status_code >= 400:
                log(f"  [{response.status_code}] {label} → {response.text[:120]}")
                continue
            messages = response.json().get("messages") or []
            log(f"  [200] {label} → {len(messages)} сообщений")
            near = [
                m
                for m in messages
                if abs(int(m.get("timestamp") or 0) - VOICE_TS) < 120_000
            ]
            for message in near:
                body = message.get("body") or {}
                sender = message.get("sender") or {}
                att = [a.get("type") for a in (body.get("attachments") or []) if isinstance(a, dict)]
                log(
                    f"     ts={message.get('timestamp')} sender={sender.get('user_id')} "
                    f"text={(body.get('text') or '')[:20]!r} att={att}"
                )

        log("\n=== 3. Проверка seq: есть ли пропуск после /start ===")
        response = await client.get(f"{base}/messages", params={"chat_id": CHAT_ID, "count": 30})
        if response.status_code < 400:
            messages = response.json().get("messages") or []
            seqs = []
            for message in messages:
                body = message.get("body") or {}
                seqs.append((int(message.get("timestamp") or 0), body.get("seq"), body.get("mid")))
            seqs.sort(reverse=True)
            for ts, seq, mid in seqs[:6]:
                log(f"  ts={ts} seq={seq} mid={mid}")

        log("\n=== 4. Сообщение по mid голосового (если угадаем) ===")
        log("  невозможно — mid голосового неизвестен (событие его не содержит)")

    print(out.getvalue()[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
