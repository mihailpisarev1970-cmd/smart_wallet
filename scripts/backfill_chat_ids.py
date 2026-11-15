"""Заполнить ``users.last_chat_id`` реальными chat_id диалогов.

chat_id диалога **не равен** ``max_user_id`` (проверено: 461841194 против
72910765), поэтому для существующих пользователей нужно узнать chat_id через
``GET /messages?chat_id=<max_user_id>``… но этот способ не работает.

Используем другой путь: пробуем ``GET /chats/{max_user_id}`` — если MAX
принимает max_user_id как chat_id диалога, берём ``chat_id`` из ответа.
Иначе оставляем поле пустым: оно заполнится при первом сообщении.

Отчёт: ``.report/backfill_chats.txt``.
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
from bot.db import Database  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "backfill_chats.txt"

#: Известные соответствия max_user_id → chat_id (из GET /messages).
KNOWN_CHATS: dict[int, int] = {
    72910765: 461841194,
}


async def main() -> int:
    settings = get_settings()
    base = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    db = Database(settings.database_url, min_size=1, max_size=2)
    await db.connect()
    try:
        rows = await db.fetch(
            "SELECT id, max_user_id, first_name, last_chat_id FROM users "
            "WHERE is_active = TRUE ORDER BY id"
        )
        log(f"Пользователей: {len(rows)}")

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20.0), verify=verify_option(), headers=headers
        ) as client:
            for row in rows:
                user_id = int(row["id"])
                max_user_id = int(row["max_user_id"])
                if row["last_chat_id"]:
                    log(f"  user={user_id} max={max_user_id}: уже есть chat={row['last_chat_id']}")
                    continue

                # 1. Известное соответствие (получено из реальной истории чата).
                known_chat = KNOWN_CHATS.get(max_user_id)
                if known_chat:
                    await db.execute(
                        "UPDATE users SET last_chat_id = $2, updated_at = NOW() WHERE id = $1",
                        user_id,
                        known_chat,
                    )
                    log(f"  user={user_id} max={max_user_id}: chat={known_chat} (известное)")
                    continue

                try:
                    response = await client.get(f"{base}/chats/{max_user_id}")
                except Exception as exc:
                    log(f"  user={user_id} max={max_user_id}: ОШИБКА {type(exc).__name__}")
                    continue

                if response.status_code != 200:
                    log(f"  user={user_id} max={max_user_id}: HTTP {response.status_code}")
                    continue

                payload = response.json()
                chat_id = payload.get("chat_id")
                log(
                    f"  user={user_id} max={max_user_id}: chat_id={chat_id} "
                    f"type={payload.get('type')}"
                )
                if chat_id:
                    await db.execute(
                        "UPDATE users SET last_chat_id = $2, updated_at = NOW() WHERE id = $1",
                        user_id,
                        int(chat_id),
                    )
    finally:
        await db.close()

    # Итоговое состояние
    db2 = Database(settings.database_url, min_size=1, max_size=1)
    await db2.connect()
    try:
        rows = await db2.fetch(
            "SELECT id, max_user_id, last_chat_id, first_name FROM users "
            "WHERE is_active = TRUE ORDER BY id"
        )
        log("\nИтог:")
        for row in rows:
            log(
                f"  user={row['id']} max={row['max_user_id']} "
                f"chat={row['last_chat_id']} name={row['first_name']!r}"
            )
    finally:
        await db2.close()

    print(out.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
