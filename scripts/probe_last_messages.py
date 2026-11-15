"""Мгновенная проверка: что MAX отдаёт для последних сообщений.

Читает последние обновления (``GET /updates`` без marker = только последнее,
затем с marker — все остальные) и печатает **полную структуру** сообщений,
включая вложения. Это нужно, чтобы увидеть, как именно выглядит голосовое.

Запуск (бот должен быть ОСТАНОВЛЕН, иначе конфликт за marker)::

    python -m scripts.probe_last_messages
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

REPORT = PROJECT_ROOT / ".report" / "last_messages.json"


async def main() -> int:
    settings = get_settings()
    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=30
    ) as client:
        try:
            batch = await client.get_updates(marker=None, timeout=5, limit=100)
        except MaxAPIError as exc:
            print(f"ОШИБКА: {exc}")
            return 1

    updates = batch.get("updates") or []
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(
        json.dumps({"marker": batch.get("marker"), "updates": updates},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    out = io.StringIO()
    out.write(f"Всего событий: {len(updates)}, marker={batch.get('marker')}\n")

    for update in updates:
        update_type = update.get("update_type")
        message = update.get("message") or {}
        body = message.get("body") or {}
        sender = message.get("sender") or update.get("user") or {}
        out.write(f"\n--- {update_type} от user_id={sender.get('user_id')} ---\n")
        out.write(f"  text: {body.get('text')!r}\n")

        attachments = body.get("attachments") or []
        if attachments:
            out.write(f"  ВЛОЖЕНИЙ: {len(attachments)}\n")
            for index, attachment in enumerate(attachments, start=1):
                out.write(f"  [{index}] type={attachment.get('type')!r}\n")
                out.write(
                    "      "
                    + json.dumps(attachment, ensure_ascii=False, indent=6)[:1500].replace(
                        "\n", "\n      "
                    )
                    + "\n"
                )
        else:
            out.write("  без вложений\n")

    text = out.getvalue()
    (PROJECT_ROOT / ".report" / "last_messages.txt").write_text(text, encoding="utf-8")
    print(text[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
