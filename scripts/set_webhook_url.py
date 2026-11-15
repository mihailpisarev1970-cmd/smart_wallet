"""Переключить webhook-подписку MAX на произвольный URL.

    python -m scripts.set_webhook_url https://example.trycloudflare.com/capture
    python -m scripts.set_webhook_url --restore     # вернуть адрес из .env
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxClient  # noqa: E402
from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import build_ca_bundle  # noqa: E402

UPDATE_TYPES = [
    "message_created",
    "message_callback",
    "message_edited",
    "bot_started",
    "bot_stopped",
]


async def main(new_url: str) -> int:
    settings = reload_settings()
    build_ca_bundle()

    async with MaxClient(settings.max_bot_token, settings.max_api_base_url, timeout=30.0) as api:
        current = await api.get_subscriptions()
        entries = current.get("subscriptions") or []
        print("Текущие подписки:", entries)

        for entry in entries:
            old_url = entry.get("url") if isinstance(entry, dict) else entry
            if old_url:
                await api.unsubscribe_webhook(str(old_url))
                print("Удалена:", old_url)

        result = await api.subscribe_webhook(new_url, update_types=UPDATE_TYPES)
        print(f"Новая подписка: {new_url} -> {result}")

        check = await api.get_subscriptions()
        print("Проверка:", check.get("subscriptions"))
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    use_default = arg in {"", "--restore"}
    url = reload_settings().public_max_webhook_url if use_default else arg
    print("URL:", url)
    sys.exit(asyncio.run(main(url)))
