"""Диагностика long polling: что реально приходит от MAX.

Запуск::

    python -m scripts.check_polling --seconds 60

Печатает все события, которые отдаёт ``GET /updates`` за указанное время,
включая ``message_callback`` (нажатия кнопок). Результат пишется в
``.report/polling.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxAPIError, MaxClient  # noqa: E402
from bot.config import get_settings  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "polling.txt"


async def main(seconds: int) -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    log(f"Слушаю события {seconds} с (timeout=20, limit=100)...")
    marker: int | None = None
    deadline = time.monotonic() + seconds
    total = 0

    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=40
    ) as client:
        while time.monotonic() < deadline:
            remaining = max(5, int(deadline - time.monotonic()))
            try:
                batch = await client.get_updates(
                    marker=marker, timeout=min(20, remaining), limit=100
                )
            except MaxAPIError as exc:
                log(f"ОШИБКА get_updates: {exc}")
                await asyncio.sleep(2)
                continue

            marker = batch.get("marker", marker)
            updates = batch.get("updates") or []
            log(f"[{time.strftime('%H:%M:%S')}] marker={marker} событий={len(updates)}")
            for update in updates:
                total += 1
                update_type = update.get("update_type")
                message = update.get("message") or {}
                body = message.get("body") or {}
                sender = message.get("sender") or update.get("user") or {}
                callback = update.get("callback") or {}
                log(
                    f"  {update_type}: sender={sender.get('user_id')} "
                    f"text={ (body.get('text') or '')[:40]!r} "
                    f"callback_id={callback.get('callback_id')} "
                    f"payload={callback.get('payload')!r}"
                )
                if update_type == "message_callback":
                    log("  ПОЛНЫЙ UPDATE: " + repr(update)[:1200])

    log(f"Всего событий: {total}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.seconds)))
