"""Проверка AI-помощника на живом запросе (с контекстом финансов из БД).

Запуск::

    python -m scripts.check_assistant --question "На что я больше всего тратил?"

Отчёт: ``.report/assistant.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import traceback
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.db import Database  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "assistant.txt"
TEST_USER_ID = 999000333  # пользователь, наполненный скриптом check_ai_flow


class FakeAPI:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": f"mid.{len(self.sent)}"}}}

    async def answer_callback(self, callback_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}


async def main(question: str) -> int:
    import bot.handlers  # noqa: F401
    from bot.dispatcher import Dispatcher
    from bot.states import Screen

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

    user, _ = await dispatcher.users.ensure_user(TEST_USER_ID, first_name="Тест AI")
    if not user.onboarding_completed:
        await dispatcher.users.complete_onboarding(user.id, "RUB", "Europe/Moscow")
    await dispatcher.states.set(user.id, Screen.AI_ASSISTANT, {})
    await db.execute(
        "UPDATE users SET ai_requests_used = 0, ai_subscription_status = 'free' WHERE id = $1",
        user.id,
    )
    before = await db.fetchval("SELECT ai_requests_used FROM users WHERE id = $1", user.id)

    log(f"Вопрос: {question!r}")
    log(f"AI-запросов до: {before}")
    try:
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
                    "body": {"mid": "mid.assist.1", "text": question},
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
    except Exception:
        log("ИСКЛЮЧЕНИЕ:")
        log(traceback.format_exc()[:2500])

    if api.sent:
        log("\nОтвет AI-помощника:")
        log(api.sent[-1].get("text", "")[:2000])
    else:
        log("ОШИБКА: бот ничего не ответил")

    after = await db.fetchval("SELECT ai_requests_used FROM users WHERE id = $1", user.id)
    log(f"\nAI-запросов после: {after}")
    await db.close()
    print(out.getvalue())
    return 0 if api.sent else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--question", default="На что я больше всего тратил в этом месяце?")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.question)))
