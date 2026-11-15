"""Сквозная проверка голосового ввода: аудио → STT → LLM → подтверждение.

Эмулирует голосовое сообщение MAX (вложение ``type="audio"``) и прогоняет
через диспетчер с фейковым клиентом: скачивание заменяется чтением локального
файла, остальные запросы реальные (STT и LLM у AI Dostup).

Запуск::

    python -m scripts.check_voice_flow

Отчёт: ``.report/voice_flow.txt``.
"""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.db import Database  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_flow.txt"
SAMPLE = PROJECT_ROOT / ".report" / "speech_sample.wav"
TEST_USER_ID = 999000444


class VoiceAPI:
    """Фейковый клиент: имитирует голосовое вложение и запоминает ответы."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.downloaded = 0

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": f"mid.{len(self.sent)}"}}}

    async def answer_callback(self, callback_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def download_attachment(self, url: str) -> bytes:
        self.downloaded += 1
        return SAMPLE.read_bytes()


async def main() -> int:
    import bot.handlers  # noqa: F401
    from bot.dispatcher import Dispatcher
    from bot.states import Screen

    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    if not SAMPLE.exists():
        log(f"Нет файла {SAMPLE}. Сначала: python -m scripts.check_voices")
        return 1

    db = Database(settings.database_url, min_size=1, max_size=3)
    await db.connect()
    api = VoiceAPI()
    dispatcher = Dispatcher(db=db, api=api, settings=settings)

    user, _ = await dispatcher.users.ensure_user(TEST_USER_ID, first_name="Тест Голос")
    if not user.onboarding_completed:
        await dispatcher.users.complete_onboarding(user.id, "RUB", "Europe/Moscow")
    await dispatcher.states.set(user.id, Screen.MAIN_MENU, {})
    await db.execute(
        "UPDATE users SET ai_requests_used = 0, ai_subscription_status = 'free' WHERE id = $1",
        user.id,
    )

    log("Голосовое сообщение (эмуляция вложения MAX):")
    log(f"  audio_type=voice, url={SAMPLE.name}")

    await dispatcher.handle_update(
        {
            "update_type": "message_created",
            "timestamp": 1,
            "message": {
                "recipient": {"chat_type": "dialog", "chat_id": 1, "user_id": TEST_USER_ID},
                "body": {
                    "mid": "mid.voice.1",
                    "text": "",
                    "attachments": [
                        {
                            "type": "audio",
                            "payload": {
                                "audio_type": "voice",
                                "url": "https://example.com/voice.wav",
                                "duration": 4000,
                            },
                        }
                    ],
                },
                "sender": {"user_id": TEST_USER_ID, "first_name": "Тест Голос", "is_bot": False},
            },
        }
    )

    log(f"\nСкачиваний аудио: {api.downloaded}")
    if not api.sent:
        log("ОШИБКА: бот ничего не ответил")
        await db.close()
        return 2

    log("Ответ бота:")
    log(api.sent[-1].get("text", "")[:800])

    used = await db.fetchval("SELECT ai_requests_used FROM users WHERE id = $1", user.id)
    log(f"\nAI-запросов списано: {used} (STT + LLM считаются как один)")

    from bot.services.ai_base import AIUsageLogger  # noqa: F401 - для полноты

    logs = await db.fetch(
        "SELECT request_type, model_used, success, audio_duration_seconds, latency_ms "
        "FROM ai_usage_log WHERE user_id = $1 ORDER BY id DESC LIMIT 3",
        user.id,
    )
    log("Лог AI:")
    for row in logs:
        log(
            f"  {row['request_type']}: модель={row['model_used']} "
            f"успех={row['success']} аудио={row['audio_duration_seconds']} "
            f"задержка={row['latency_ms']} мс"
        )

    await db.close()
    print(out.getvalue())
    return 0 if used == 1 else 3


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
