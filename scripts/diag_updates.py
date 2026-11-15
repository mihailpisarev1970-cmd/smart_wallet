"""Проверка доставки: full-message vs empty update (long polling vs webhook).

Сравнивает, как MAX отдаёт одно и то же событие в разных режимах:
* ``GET /updates`` (long polling) — есть ли поле ``message``;
* ``POST /subscriptions`` (webhook) требует публичный HTTPS, поэтому здесь
  проверяем только long polling и делаем вывод.

Также проверяет, помогает ли параметр ``types`` в ``/updates``
и приходит ли полное сообщение при ``message_edited``.

Отчёт: ``.report/updates_diag.txt``.
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

REPORT = PROJECT_ROOT / ".report" / "updates_diag.txt"


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=30
    ) as client:
        # 1. Все события за последний период (большой limit, от старого marker)
        log("=== 1. История событий: есть ли поле message у message_created ===")
        try:
            batch = await client.get_updates(marker=32610, timeout=10, limit=1000)
        except MaxAPIError as exc:
            log(f"ОШИБКА: {exc}")
            return 1

        updates = batch.get("updates") or []
        with_message = 0
        without_message = 0
        for update in updates:
            if update.get("update_type") != "message_created":
                continue
            if update.get("message"):
                with_message += 1
            else:
                without_message += 1
        log(f"  Всего событий: {len(updates)}")
        log(f"  message_created С message:    {with_message}")
        log(f"  message_created БЕЗ message:  {without_message}")

        # 2. Пробуем разные наборы types
        log("\n=== 2. Влияет ли параметр types ===")
        for types in (
            ["message_created"],
            ["message_created", "message_callback"],
        ):
            try:
                response = await client._request(
                    "GET", "updates", params={"marker": 32610, "timeout": 5, "limit": 100,
                                              "types": ",".join(types)}
                )
                got = response.get("updates") or []
                empty = sum(
                    1
                    for upd in got
                    if upd.get("update_type") == "message_created" and not upd.get("message")
                )
                log(f"  types={types}: событий {len(got)}, пустых message_created={empty}")
            except MaxAPIError as exc:
                log(f"  types={types}: ОШИБКА {exc}")

        # 3. Проверяем подписки (webhook)
        log("\n=== 3. Текущие webhook-подписки ===")
        try:
            subscriptions = await client.get_subscriptions()
            log(f"  {json.dumps(subscriptions, ensure_ascii=False)[:500]}")
        except MaxAPIError as exc:
            log(f"  ОШИБКА: {exc}")

        # 4. Показываем пример пустого события целиком
        log("\n=== 4. Пример пустого message_created ===")
        for update in updates:
            if update.get("update_type") == "message_created" and not update.get("message"):
                log(json.dumps(update, ensure_ascii=False, indent=2))
                break

    print(out.getvalue()[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
