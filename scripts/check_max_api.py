"""Проверка интеграции с MAX Bot API на живом боте (Уровень 1).

Скрипт НЕ трогает базу данных и не влияет на данные бота — он только
проверяет, что API-контракт в коде совпадает с реальным поведением MAX.

Запуск::

    python -m scripts.check_max_api                # только чтение
    python -m scripts.check_max_api --user-id N    # + тест отправки сообщения
    python -m scripts.check_max_api --user-id N --listen 60

Сценарий интерактивной проверки:
1. Запустите ``--user-id <ваш id> --listen 60``.
2. Бот пришлёт сообщение с кнопкой «Проверить callback».
3. Нажмите кнопку — скрипт распечатает ``message_callback``
   и проверит работу ``POST /answers``.

Где узнать свой user_id: напишите боту любое сообщение, пока скрипт
работает в режиме ``--listen`` — в событии ``message_created`` будет
``message.sender.user_id``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Запуск как `python -m scripts.check_max_api` из корня проекта.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.api import MaxAPIError, MaxClient
from bot.config import get_settings


def _dump(title: str, payload: Any) -> None:
    """Печать JSON с русскими символами без экранирования."""
    print(f"\n--- {title} " + "-" * max(0, 60 - len(title)))
    print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])


def _keyboard_demo() -> list[dict[str, Any]]:
    """Inline-клавиатура: callback-кнопка и кнопка-ссылка."""
    return [
        {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [{"type": "callback", "text": "Проверить callback", "payload": "check:callback"}],
                    [{"type": "link", "text": "Документация MAX", "url": "https://dev.max.ru/docs-api"}],
                ]
            },
        }
    ]


async def check_static(client: MaxClient) -> None:
    """GET /me и GET /subscriptions — проверка авторизации."""
    me = await client.get_me()
    _dump("GET /me", me)
    print(f"OK: бот {me.get('name')} (@{me.get('username')}), user_id={me.get('user_id')}")

    try:
        subscriptions = await client.get_subscriptions()
        _dump("GET /subscriptions", subscriptions)
    except MaxAPIError as exc:
        print(f"WARN GET /subscriptions: {exc}")


async def send_demo(client: MaxClient, user_id: int) -> str | None:
    """Отправить демо-сообщение с клавиатурой, вернуть message_id."""
    message = await client.send_message(
        user_id=user_id,
        text="<b>Тест API «Умный кошелёк»</b>\n\nЕсли видите эту клавиатуру — "
        "отправка сообщений и inline-клавиатур работает.\nНажмите кнопку ниже.",
        attachments=_keyboard_demo(),
        format="html",
    )
    _dump("POST /messages (response)", message)
    body = message.get("message", message)
    mid = (body.get("body") or {}).get("mid") or body.get("mid")
    print(f"OK: сообщение отправлено, message_id={mid}")
    return str(mid) if mid else None


async def drain_updates(client: MaxClient, seconds: int, user_id: int | None) -> None:
    """Слушаем события и демонстрируем обработку message_callback / /answers."""
    print(f"\n>> Слушаю события {seconds} с ... (Ctrl+C для выхода)")
    marker: int | None = None
    deadline = time.monotonic() + seconds
    seen_callback: set[str] = set()

    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        try:
            batch = await client.get_updates(marker=marker, timeout=min(20, remaining), limit=100)
        except MaxAPIError as exc:
            print(f"WARN get_updates: {exc}")
            await asyncio.sleep(2)
            continue

        new_marker = batch.get("marker")
        if new_marker is not None:
            marker = new_marker

        for update in batch.get("updates", []):
            update_type = update.get("update_type")
            print(
                f"\n<< update_type={update_type} chat_id={update.get('chat_id')} "
                f"ts={update.get('timestamp')}"
            )

            if update_type == "message_created":
                message = update.get("message", {})
                sender = message.get("sender", {})
                text = (message.get("body") or {}).get("text", "")
                print(
                    f"   sender.user_id={sender.get('user_id')} "
                    f"name={sender.get('first_name')} text={text[:120]!r}"
                )
                if user_id is None and sender.get("user_id"):
                    print(
                        f"   INFO: ваш user_id = {sender.get('user_id')} "
                        f"(для следующего запуска: --user-id {sender.get('user_id')})"
                    )

            elif update_type == "message_callback":
                _dump("message_callback", update)
                callback = update.get("callback") or {}
                callback_id = callback.get("callback_id") or callback.get("id") or ""
                button_payload = callback.get("payload") or ""
                print(f"   callback_id={callback_id!r} payload={button_payload!r}")

                # Проверяем POST /answers (ответ на callback).
                if callback_id and str(callback_id) not in seen_callback:
                    seen_callback.add(str(callback_id))
                    try:
                        result = await client.answer_callback(
                            str(callback_id), notification="Callback получен"
                        )
                        _dump("POST /answers (response)", result)
                        print("OK: POST /answers работает")
                    except MaxAPIError as exc:
                        print(f"WARN POST /answers: {exc}")

                # Реакция бота: обычное сообщение.
                if user_id:
                    await client.send_message(
                        user_id=user_id,
                        text=f"Кнопка нажата: payload={button_payload!r}. "
                        "Обработка callback работает.",
                    )

            elif update_type in {"bot_started", "bot_stopped", "message_removed"}:
                _dump(update_type, update)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка MAX Bot API")
    parser.add_argument("--user-id", type=int, default=None, help="Кому отправить тест")
    parser.add_argument("--listen", type=int, default=0, help="Сколько секунд слушать события")
    parser.add_argument("--no-static", action="store_true", help="Пропустить GET /me")
    args = parser.parse_args()

    settings = get_settings()
    print(f"API: {settings.max_api_base_url}")
    print(
        f"Токен: {settings.max_bot_token[:8]}...{settings.max_bot_token[-4:]} "
        f"({len(settings.max_bot_token)} символов)"
    )

    async with MaxClient(
        settings.max_bot_token,
        settings.max_api_base_url,
        timeout=settings.max_http_timeout_seconds,
    ) as client:
        if not args.no_static:
            await check_static(client)
        if args.user_id:
            await send_demo(client, args.user_id)
        if args.listen:
            await drain_updates(client, args.listen, args.user_id)

    print("\nOK: проверка завершена")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        print("\nПрервано пользователем")

