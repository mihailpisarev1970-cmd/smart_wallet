"""Живая проверка AI-цикла через диспетчер (как реальное сообщение в MAX).

Эмулирует событие ``message_created`` с фразой и прогоняет его через
``Dispatcher.handle_update``: проверяет, что бот распознал операцию,
предложил подтверждение и что запись создаётся по кнопке «Записать».

Запуск::

    python -m scripts.check_ai_flow --phrase "Потратил 1250 на продукты"

Отчёт: ``.report/ai_flow.txt``. В MAX ничего не отправляется — используется
фейковый API-клиент, реальные запросы идут только к LLM.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.db import Database  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "ai_flow.txt"
TEST_USER_ID = 999000333


class FakeAPI:
    """Запоминает отправленные сообщения вместо реальной отправки в MAX."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": f"mid.{len(self.sent)}"}}}

    async def answer_callback(self, callback_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def download_attachment(self, url: str) -> bytes:
        return b""


async def main(phrase: str) -> int:
    import bot.handlers  # noqa: F401 - регистрирует обработчики
    from bot.dispatcher import Dispatcher

    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    db = Database(settings.database_url, min_size=1, max_size=3)
    await db.connect()
    api = FakeAPI()
    dispatcher = Dispatcher(db=db, api=api, settings=settings)

    # Готовим пользователя с завершённым онбордингом
    user, _ = await dispatcher.users.ensure_user(TEST_USER_ID, first_name="Тест AI")
    if not user.onboarding_completed:
        await dispatcher.users.complete_onboarding(user.id, "RUB", "Europe/Moscow")
    from bot.states import Screen

    await dispatcher.states.set(user.id, Screen.MAIN_MENU, {})
    await db.execute(
        "UPDATE users SET ai_requests_used = 0, ai_subscription_status = 'free' WHERE id = $1",
        user.id,
    )

    log(f"Фраза: {phrase!r}")
    log("1) Отправляем сообщение пользователя...")

    # Вызываем обработчик напрямую, чтобы видеть исключения (диспетчер их ловит).
    import traceback

    for attempt, dispatcher_call in enumerate(["direct", "dispatch"], start=1):
        try:
            if dispatcher_call == "direct":
                await dispatcher._dispatch(
                    {
                        "update_type": "message_created",
                        "timestamp": 1,
                        "message": {
                            "recipient": {
                                "chat_type": "dialog",
                                "chat_id": 1,
                                "user_id": TEST_USER_ID,
                            },
                            "body": {"mid": f"mid.flow.{attempt}", "text": phrase},
                            "sender": {
                                "user_id": TEST_USER_ID,
                                "first_name": "Тест AI",
                                "is_bot": False,
                            },
                        },
                    },
                    "message_created",
                    {"user_id": TEST_USER_ID, "first_name": "Тест AI", "is_bot": False},
                    TEST_USER_ID,
                )
            else:
                break
        except Exception:
            log("   ИСКЛЮЧЕНИЕ при обработке:")
            log(traceback.format_exc()[:2000])
            break

    if not api.sent:
        log("ОШИБКА: бот ничего не ответил")
        await db.close()
        return 1

    reply = api.sent[-1]
    log(f"   Ответ бота: {reply.get('text')[:400]!r}")
    keyboard = reply.get("attachments") or []
    save_payload = None
    for attachment in keyboard:
        if attachment.get("type") != "inline_keyboard":
            continue
        for row in attachment.get("payload", {}).get("buttons", []):
            for button in row:
                log(f"   Кнопка: {button.get('text')!r} -> {button.get('payload')!r}")
                if str(button.get("payload", "")).startswith("ai:save"):
                    save_payload = button["payload"]

    used = await db.fetchval("SELECT ai_requests_used FROM users WHERE id = $1", user.id)
    log(f"2) AI-запросов списано: {used}")

    if save_payload is None:
        log("   Подтверждение не предложено (нет кнопки ai:save) — фраза не распознана")
        await db.close()
        return 2

    log("3) Нажимаем «Записать»...")
    try:
        await dispatcher._dispatch(
            {
                "update_type": "message_callback",
                "timestamp": 2,
                "callback": {
                    "callback_id": "cb.flow.1",
                    "payload": save_payload,
                    "user": {
                        "user_id": TEST_USER_ID,
                        "first_name": "Тест AI",
                        "is_bot": False,
                    },
                },
                "message": {
                    "recipient": {
                        "chat_type": "dialog",
                        "chat_id": 1,
                        "user_id": TEST_USER_ID,
                    },
                    "body": {"mid": "mid.flow.1", "text": reply.get("text", "")},
                    "sender": {"user_id": 1, "is_bot": True},
                },
            },
            "message_callback",
            {"user_id": TEST_USER_ID, "first_name": "Тест AI", "is_bot": False},
            TEST_USER_ID,
        )
    except Exception:
        log("   ИСКЛЮЧЕНИЕ при записи:")
        log(traceback.format_exc()[:2500])
    if api.sent:
        log(f"   Ответ бота: {api.sent[-1].get('text')[:400]!r}")
    state = await dispatcher.states.get(user.id)
    log(f"   Состояние: screen={state.screen} data={list(state.data)}")

    from bot.services.transactions import TransactionService

    records = await TransactionService(db).last(user.id, limit=3)
    log("4) Операции в БД:")
    for record in records:
        log(
            f"   #{record.id} {record.type_label} {record.amount} {record.currency} "
            f"— {record.category_name} ({record.transaction_date}), источник={record.source}"
        )

    await db.close()
    print(out.getvalue())
    return 0 if records else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phrase", default="Потратил 1250 на продукты")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.phrase)))
