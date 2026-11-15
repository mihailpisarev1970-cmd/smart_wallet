"""Тесты роутера и разбора событий MAX."""

from __future__ import annotations

from typing import Any

from bot.router import Router
from bot.update_parser import (
    extract_attachments,
    extract_chat_id,
    extract_message_id,
    extract_sender,
    extract_text,
    find_voice_attachment,
    parse_payload,
    voice_url,
)


class _Ctx:
    """Минимальная заглушка контекста для проверки маршрутизации."""

    def __init__(self, event: str, text: str = "", args: list[str] | None = None) -> None:
        self.event = event
        self.text = text
        self.args = args or []


async def test_callback_routing(router: Router) -> None:
    calls: list[str] = []

    @router.callback("tx:new")
    async def handler(ctx: Any) -> None:
        calls.append(ctx.text)

    result = await router.dispatch(_Ctx("callback", "tx:new", ["expense"]))
    assert calls == ["tx:new"]
    assert result == []


async def test_command_routing_case_insensitive(router: Router) -> None:
    calls: list[str] = []

    @router.command("/start")
    async def handler(ctx: Any) -> None:
        calls.append(ctx.event)

    await router.dispatch(_Ctx("command", "/START"))
    assert calls == ["command"]


async def test_unknown_callback_goes_to_fallback(router: Router) -> None:
    calls: list[str] = []

    async def fallback(ctx: Any) -> None:
        calls.append("fallback")

    router.set_fallback(fallback)
    await router.dispatch(_Ctx("callback", "unknown:action"))
    assert calls == ["fallback"]


async def test_prefix_routing(router: Router) -> None:
    calls: list[str] = []

    @router.callback("tx:", prefix=True)
    async def handler(ctx: Any) -> None:
        calls.append(ctx.text)

    await router.dispatch(_Ctx("callback", "tx:save"))
    assert calls == ["tx:save"]


async def test_text_and_voice_handlers(router: Router) -> None:
    calls: list[str] = []

    @router.text
    async def text_handler(ctx: Any) -> None:
        calls.append("text")

    @router.voice
    async def voice_handler(ctx: Any) -> None:
        calls.append("voice")

    await router.dispatch(_Ctx("message", "привет"))
    await router.dispatch(_Ctx("voice"))
    assert calls == ["text", "voice"]


def test_parse_payload() -> None:
    """Аргумент отделяется, если это число или известный код."""
    assert parse_payload("tx:cat:42") == ("tx:cat", ["42"])
    assert parse_payload("history:edit_field:amount:42") == ("history:edit_field:amount", ["42"])
    # Коды-аргументы (тип операции, валюта, период) отделяются.
    assert parse_payload("tx:new:expense") == ("tx:new", ["expense"])
    assert parse_payload("tx:new:income") == ("tx:new", ["income"])
    assert parse_payload("onboarding:currency:RUB") == ("onboarding:currency", ["RUB"])
    assert parse_payload("stats:show:month") == ("stats:show", ["month"])
    # Без аргумента payload — это действие целиком (роутер найдёт обработчик).
    assert parse_payload("onboarding:start") == ("onboarding:start", [])
    assert parse_payload("ai:save") == ("ai:save", [])
    assert parse_payload("menu:main") == ("menu:main", [])
    assert parse_payload("history:page") == ("history:page", [])
    assert parse_payload("menu") == ("menu", [])
    assert parse_payload(None) == ("", [])
    assert parse_payload("") == ("", [])


def test_extract_actor_for_callback_uses_callback_user() -> None:
    """В message_callback поле message.sender — сам бот, а не пользователь.

    Это регрессионный тест: раньше бот отбрасывал такие события как «от бота».
    """
    from bot.dispatcher import Dispatcher

    update = {
        "update_type": "message_callback",
        "callback": {
            "callback_id": "abc",
            "payload": "onboarding:start",
            "user": {"user_id": 72910765, "first_name": "Михаил", "is_bot": False},
        },
        "message": {
            "sender": {"user_id": 534750343, "first_name": "Умный кошелёк", "is_bot": True},
            "recipient": {"chat_id": 461841194, "user_id": 72910765},
        },
    }
    actor = Dispatcher._extract_actor(update, "message_callback")
    assert actor["user_id"] == 72910765
    assert not actor["is_bot"]


def test_extract_actor_for_message_uses_sender() -> None:
    from bot.dispatcher import Dispatcher

    update = _update("привет")
    actor = Dispatcher._extract_actor(update, "message_created")
    assert actor["user_id"] == 777


def test_update_id_fits_db_column() -> None:
    """update_id должен помещаться в varchar(128) после нормализации."""
    from bot.db.idempotency import IdempotencyGuard

    long_callback = "message_callback:" + "f9LHodD0cO" * 15  # ~200 символов
    key = IdempotencyGuard._key(long_callback)
    assert len(key) <= 128
    # Одинаковые id дают одинаковый ключ, разные — разные.
    assert IdempotencyGuard._key(long_callback) == key
    assert IdempotencyGuard._key(long_callback + "x") != key
    assert IdempotencyGuard._key("short-id") == "short-id"


def _update(text: str = "привет", **extra: Any) -> dict[str, Any]:
    message = {
        "body": {"mid": "mid.1", "text": text},
        "sender": {"user_id": 777, "first_name": "Иван", "username": "ivan"},
        "recipient": {"chat_id": 555, "chat_type": "dialog"},
    }
    return {"update_type": "message_created", "timestamp": 1, "message": message, **extra}


def test_extract_helpers() -> None:
    update = _update("Потратил 1250")
    assert extract_text(update) == "Потратил 1250"
    assert extract_message_id(update) == "mid.1"
    assert extract_chat_id(update) == 555
    assert extract_sender(update)["user_id"] == 777


def test_extract_voice_attachment() -> None:
    voice = {
        "type": "audio",
        "payload": {"audio_type": "voice", "url": "https://example.com/a.ogg", "duration": 5000},
    }
    update = _update("")
    update["message"]["body"]["attachments"] = [voice]
    attachments = extract_attachments(update)
    found = find_voice_attachment(attachments)
    assert found is voice
    assert voice_url(found) == "https://example.com/a.ogg"


def test_find_voice_attachment_ignores_others() -> None:
    attachments = [{"type": "image", "payload": {"url": "x"}}]
    assert find_voice_attachment(attachments) is None
