"""Управление webhook-подпиской MAX из командной строки.

Команды::

    python -m scripts.manage_webhook show        # список подписок
    python -m scripts.manage_webhook register    # подписаться (url из .env)
    python -m scripts.manage_webhook remove      # отписаться
    python -m scripts.manage_webhook back-to-polling  # вернуть long polling

Отчёт выводится в консоль и в ``.report/webhook.txt``.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxAuthError, MaxClient  # noqa: E402
from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import build_ca_bundle  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "webhook.txt"

#: События, которые нужны боту.
UPDATE_TYPES = [
    "message_created",
    "message_callback",
    "message_edited",
    "message_removed",
    "bot_started",
    "bot_stopped",
]


async def main(command: str) -> int:
    settings = reload_settings()
    build_ca_bundle()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    url = settings.public_max_webhook_url
    log(f"Режим апдейтов: {settings.max_updates_mode}")
    log(f"Публичный URL вебхука: {url or '(не задан)'}")
    log()

    async with MaxClient(settings.max_bot_token, settings.max_api_base_url, timeout=30.0) as api:
        try:
            if command == "show":
                result = await api.get_subscriptions()
                log("Текущие подписки:")
                log(json.dumps(result, ensure_ascii=False, indent=2))

            elif command == "register":
                if not url:
                    log("ОШИБКА: задайте WEBHOOK_BASE_URL или MAX_WEBHOOK_URL в .env")
                    return 2
                result = await api.subscribe_webhook(url, update_types=UPDATE_TYPES)
                log(f"Подписка создана: {url}")
                log(json.dumps(result, ensure_ascii=False, indent=2))

            elif command == "remove":
                if not url:
                    log("ОШИБКА: задайте WEBHOOK_BASE_URL или MAX_WEBHOOK_URL в .env")
                    return 2
                result = await api.unsubscribe_webhook(url)
                log(f"Подписка удалена: {url}")
                log(json.dumps(result, ensure_ascii=False, indent=2))

            elif command == "back-to-polling":
                # Возврат к long polling: снимаем все подписки.
                subscriptions = await api.get_subscriptions()
                entries = subscriptions.get("subscriptions") or []
                if not entries:
                    log("Подписок нет — polling уже активен")
                for entry in entries:
                    entry_url = entry.get("url") if isinstance(entry, dict) else str(entry)
                    if not entry_url:
                        continue
                    await api.unsubscribe_webhook(entry_url)
                    log(f"Удалена подписка: {entry_url}")
                log("\nТеперь установите MAX_UPDATES_MODE=polling и перезапустите бота")

            else:
                log(f"Неизвестная команда: {command}")
                return 3

        except MaxAuthError:
            log("ОШИБКА: токен бота недействителен")
            return 4
        except Exception as exc:
            log(f"ОШИБКА: {type(exc).__name__}: {exc}")
            return 5

    print(out.getvalue())
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "show"
    sys.exit(asyncio.run(main(command)))
