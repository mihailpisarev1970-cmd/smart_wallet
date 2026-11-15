"""Живое сравнение: голосовое сообщение проходит весь путь.

Слушает события MAX; когда приходит сообщение с аудио, показывает, что именно
пришло, и как его классифицирует бот. Результат — в ``.report/voice_live.txt``.

Запуск (при работающем боте НЕ нужен — конфликтует за marker)::

    python -m scripts.probe_voice_message --seconds 60

Отправьте в MAX голосовое сообщение в течение указанного времени.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxAPIError, MaxClient  # noqa: E402
from bot.config import get_settings  # noqa: E402
from bot.update_parser import find_voice_attachment, voice_duration, voice_url  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_live.txt"


async def main(seconds: int) -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    log(f"Слушаю {seconds} с. Отправьте голосовое сообщение в MAX.")
    marker: int | None = None
    deadline = time.monotonic() + seconds

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
                log(f"ОШИБКА: {exc}")
                await asyncio.sleep(2)
                continue
            marker = batch.get("marker", marker)

            for update in batch.get("updates") or []:
                update_type = update.get("update_type")
                message = update.get("message") or {}
                body = message.get("body") or {}
                attachments = body.get("attachments") or []
                types = [a.get("type") for a in attachments if isinstance(a, dict)]
                voice = find_voice_attachment(attachments)

                log(
                    f"\n[{time.strftime('%H:%M:%S')}] {update_type}: "
                    f"text={(body.get('text') or '')[:50]!r} attachments={types}"
                )
                if voice:
                    log(f"  Голосовое найдено: url={voice_url(voice)} "
                        f"длительность={voice_duration(voice)} с")
                elif types:
                    log("  Вложения без аудио")
                    log(f"  ПОЛНОЕ СООБЩЕНИЕ: {json.dumps(body, ensure_ascii=False)[:1500]}")

    log("\nГотово")
    print(out.getvalue())
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.seconds)))
