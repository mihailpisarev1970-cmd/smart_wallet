"""Тесты восстановления голосовых событий (регрессия на реальный баг MAX).

MAX присылает голосовые сообщения как ``message_created`` **без** поля
``message`` — только ``timestamp``, ``update_type`` и ``user_locale``
(ни ``chat_id``, ни ``user_id``). Диспетчер должен восстановить сообщение
через ``GET /messages?chat_id=`` и обработать его как голосовое.

Регрессии из реальной эксплуатации:

* голосовое «превращалось» в старый ``/start`` — восстановитель возвращал
  первое попавшееся сообщение вместо самого свежего;
* событие отбрасывалось как «без актора», потому что ``user_id`` появляется
  только после восстановления.
"""

from __future__ import annotations

from typing import Any

import pytest

VOICE_CHAT_ID = 461841194
VOICE_USER_ID = 72910765


class FakeAPIMessages:
    """Фейковый клиент: отдаёт заранее заданную историю чата."""

    def __init__(self, messages: list[dict[str, Any]], *, per_chat: dict[int, list] | None = None):
        self._messages = messages
        self._per_chat = per_chat or {}
        self.requested_chats: list[int] = []

    async def get_messages(self, chat_id: int, *, count: int = 20) -> dict[str, Any]:
        self.requested_chats.append(chat_id)
        return {"messages": self._per_chat.get(chat_id, self._messages)}


class FakeUsers:
    """Фейковый репозиторий: список недавних чатов."""

    def __init__(self, chat_ids: list[int] | None = None) -> None:
        self._chat_ids = chat_ids or []

    async def recent_chat_ids(self, limit: int = 10) -> list[int]:
        return self._chat_ids[:limit]

    async def set_last_chat_id(self, user_id: int, chat_id: int | None) -> None:
        return None


def _voice_message(ts: int, chat_id: int = VOICE_CHAT_ID, user_id: int = VOICE_USER_ID) -> dict:
    return {
        "recipient": {"chat_type": "dialog", "chat_id": chat_id, "user_id": user_id},
        "timestamp": ts,
        "body": {
            "mid": "mid.voice.1",
            "seq": 1,
            "text": "",
            "attachments": [
                {
                    "type": "audio",
                    "payload": {
                        "audio_type": "voice",
                        "url": "https://example.com/voice.ogg",
                        "duration": 8000,
                    },
                }
            ],
        },
        "sender": {"user_id": user_id, "first_name": "Михаил", "is_bot": False},
    }


def _text_message(
    ts: int, mid: str, text: str, chat_id: int = VOICE_CHAT_ID, user_id: int = VOICE_USER_ID
) -> dict:
    return {
        "recipient": {"chat_type": "dialog", "chat_id": chat_id, "user_id": user_id},
        "timestamp": ts,
        "body": {"mid": mid, "seq": 1, "text": text, "attachments": []},
        "sender": {"user_id": user_id, "first_name": "Михаил", "is_bot": False},
    }


def _make_dispatcher(api: FakeAPIMessages, chats: list[int] | None = None):
    from bot.dispatcher import Dispatcher

    dispatcher = Dispatcher.__new__(Dispatcher)
    dispatcher.api = api
    dispatcher._known_chats = [VOICE_CHAT_ID] if chats is None else chats
    dispatcher._seen_mids = []
    dispatcher.users = FakeUsers()
    return dispatcher



async def test_restore_message_for_empty_update() -> None:
    """Пустое событие дополняется сообщением из истории чата."""
    ts = 1794122880365
    api = FakeAPIMessages([_voice_message(ts)])
    dispatcher = _make_dispatcher(api)

    update = {"update_type": "message_created", "timestamp": ts, "user_locale": "ru"}
    restored = await dispatcher._restore_message(update, "message_created")

    assert "message" in restored, "сообщение не восстановлено"
    assert restored["message"]["body"]["attachments"][0]["type"] == "audio"
    assert restored["chat_id"] == VOICE_CHAT_ID


async def test_restore_message_ignores_bot_messages() -> None:
    """Сообщения бота не подставляются вместо сообщения пользователя."""
    ts = 1794122880365
    bot_message = _voice_message(ts)
    bot_message["sender"] = {"user_id": 534750343, "is_bot": True}
    api = FakeAPIMessages([bot_message])
    dispatcher = _make_dispatcher(api)

    update = {"update_type": "message_created", "timestamp": ts}
    restored = await dispatcher._restore_message(update, "message_created")
    assert "message" not in restored


async def test_restore_message_skips_old_messages() -> None:
    """Слишком старые сообщения (вне окна) не подставляются."""
    event_ts = 1794122880365
    old_ts = event_ts - 600_000  # 10 минут назад
    api = FakeAPIMessages([_voice_message(old_ts)])
    dispatcher = _make_dispatcher(api)

    restored = await dispatcher._restore_message(
        {"update_type": "message_created", "timestamp": event_ts}, "message_created"
    )
    assert "message" not in restored


async def test_restore_prefers_newest_message() -> None:
    """РЕГРЕССИЯ: берётся самое свежее сообщение, а не первое в списке.

    В реальном баге голосовое «превращалось» в старый ``/start``, потому что
    история отдаётся новыми первыми и подставлялось первое подходящее.
    """
    event_ts = 1794126698488
    start_message = _text_message(1794126650881, "mid.start", "/start")
    voice_message = _voice_message(1794126698488)
    api = FakeAPIMessages([voice_message, start_message])
    dispatcher = _make_dispatcher(api)

    restored = await dispatcher._restore_message(
        {"update_type": "message_created", "timestamp": event_ts}, "message_created"
    )

    assert restored["message"]["body"]["text"] == "", "восстановлен старый /start"
    assert restored["message"]["body"]["attachments"][0]["type"] == "audio"


async def test_restore_skips_already_processed_mid() -> None:
    """РЕГРЕССИЯ: обработанный mid не восстанавливается повторно."""
    event_ts = 1794126698488
    api = FakeAPIMessages([_voice_message(event_ts)])
    dispatcher = _make_dispatcher(api)
    dispatcher.remember_message_id("mid.voice.1")

    restored = await dispatcher._restore_message(
        {"update_type": "message_created", "timestamp": event_ts}, "message_created"
    )
    assert "message" not in restored, "уже обработанное сообщение восстановлено повторно"



async def test_restore_not_needed_when_message_present() -> None:
    """Если ``message`` уже есть — запросов к API не делаем."""
    api = FakeAPIMessages([])
    dispatcher = _make_dispatcher(api, chats=[])

    update = {"update_type": "message_created", "timestamp": 1, "message": {"body": {}}}
    restored = await dispatcher._restore_message(update, "message_created")
    assert restored is update or restored == update
    assert api.requested_chats == [], "лишний запрос к GET /messages"


@pytest.mark.parametrize("update_type", ["message_callback", "bot_started"])
async def test_restore_ignored_for_other_events(update_type: str) -> None:
    """Для прочих событий восстановление не выполняется."""
    api = FakeAPIMessages([])
    dispatcher = _make_dispatcher(api, chats=[1])

    update = {"update_type": update_type, "timestamp": 1}
    await dispatcher._restore_message(update, update_type)
    assert api.requested_chats == []


async def test_voice_update_gets_actor_after_restore() -> None:
    """РЕГРЕССИЯ: после восстановления актёр находится (иначе событие падало).

    Событие голосового не содержит ``user_id``, поэтому до восстановления
    ``_extract_actor`` возвращает пустой объект и событие отбрасывается.
    """
    ts = 1794122880365
    api = FakeAPIMessages([_voice_message(ts)])
    dispatcher = _make_dispatcher(api)

    update = {"update_type": "message_created", "timestamp": ts, "user_locale": "ru"}
    restored = await dispatcher._restore_message(update, "message_created")
    actor = dispatcher._extract_actor(restored, "message_created")

    assert actor.get("user_id") == VOICE_USER_ID
    assert not actor.get("is_bot")


async def test_restore_checks_recent_chats_from_db() -> None:
    """chat_id из БД используется, если событие пришло без него."""
    ts = 1794122880365
    other_chat = 555000111
    api = FakeAPIMessages([], per_chat={other_chat: [_voice_message(ts, chat_id=other_chat)]})
    dispatcher = _make_dispatcher(api, chats=[])
    dispatcher.users = FakeUsers([other_chat])

    restored = await dispatcher._restore_message(
        {"update_type": "message_created", "timestamp": ts}, "message_created"
    )
    assert restored["chat_id"] == other_chat
    assert other_chat in api.requested_chats


async def test_restore_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сообщение появилось в истории не сразу — повторная попытка помогает."""
    import bot.dispatcher as dispatcher_module

    monkeypatch.setattr(dispatcher_module, "RESTORE_DELAY_SECONDS", 0)
    ts = 1794122880365

    class LateAPI:
        """Первая попытка — пусто, вторая — сообщение найдено."""

        def __init__(self) -> None:
            self.calls = 0

        async def get_messages(self, chat_id: int, *, count: int = 20) -> dict[str, Any]:
            self.calls += 1
            if self.calls < 2:
                return {"messages": []}
            return {"messages": [_voice_message(ts)]}

    dispatcher = _make_dispatcher(LateAPI())  # type: ignore[arg-type]
    restored = await dispatcher._restore_message(
        {"update_type": "message_created", "timestamp": ts}, "message_created"
    )
    assert "message" in restored


def test_remember_message_id_limits_size() -> None:
    """Список обработанных mid не растёт бесконечно."""
    from bot.dispatcher import SEEN_MIDS_LIMIT

    api = FakeAPIMessages([])
    dispatcher = _make_dispatcher(api, chats=[])

    for index in range(SEEN_MIDS_LIMIT + 50):
        dispatcher.remember_message_id(f"mid.{index}")

    assert len(dispatcher._seen_mids) == SEEN_MIDS_LIMIT
    assert dispatcher._seen_mids[-1] == f"mid.{SEEN_MIDS_LIMIT + 49}"


def test_voice_transcription_from_max() -> None:
    """MAX присылает готовую транскрипцию — STT не нужен."""
    from bot.update_parser import voice_transcription

    attachment = {
        "type": "audio",
        "payload": {"audio_type": "voice", "transcription": "Потратил 1250 на продукты"},
    }
    assert voice_transcription(attachment) == "Потратил 1250 на продукты"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"audio_type": "voice"},
        {"transcription": ""},
        {"transcription": "   "},
        {"transcription": None},
    ],
)
def test_voice_transcription_absent(payload: dict) -> None:
    """Пустая или отсутствующая транскрипция → ``None`` (уходим в STT)."""
    from bot.update_parser import voice_transcription

    assert voice_transcription({"type": "audio", "payload": payload}) is None


