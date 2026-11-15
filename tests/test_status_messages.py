"""Тесты статусных сообщений (долгие операции).

Голосовое распознавание занимает 15–40 секунд. Без промежуточного
сообщения пользователь думает, что бот завис (реальная жалоба).
"""

from __future__ import annotations

from typing import Any

from bot.context import Context


class FakeAPI:
    """Клиент, запоминающий вызовы send/edit/delete."""

    def __init__(self, *, mid: str | None = "mid.status.1", fail_send: bool = False) -> None:
        self._mid = mid
        self._fail_send = fail_send
        self.sent: list[dict[str, Any]] = []
        self.edited: list[tuple[str, str]] = []
        self.deleted: list[str] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        if self._fail_send:
            raise RuntimeError("network")
        self.sent.append(kwargs)
        return {"body": {"mid": self._mid}} if self._mid else {}

    async def edit_message(self, message_id: str, **kwargs: Any) -> dict[str, Any]:
        self.edited.append((message_id, kwargs.get("text", "")))
        return {}

    async def delete_message(self, message_id: str) -> dict[str, Any]:
        self.deleted.append(message_id)
        return {}


def make_context(api: FakeAPI) -> Context:
    """Собрать минимальный Context для тестов (без БД)."""
    ctx = Context.__new__(Context)
    ctx.api = api
    ctx.max_user_id = 72910765
    return ctx


async def test_send_status_returns_mid() -> None:
    """Статус отправляется и возвращает mid для последующей замены."""
    api = FakeAPI(mid="mid.42")
    ctx = make_context(api)

    mid = await ctx.send_status("🎤 Распознаю речь…")

    assert mid == "mid.42"
    assert len(api.sent) == 1
    assert "Распознаю" in api.sent[0]["text"]
    assert api.sent[0]["user_id"] == 72910765


async def test_send_status_handles_api_failure() -> None:
    """Сбой отправки статуса не ломает сценарий — возвращается None."""
    api = FakeAPI(fail_send=True)
    ctx = make_context(api)

    assert await ctx.send_status("🎤 Распознаю…") is None


async def test_send_status_without_mid_in_response() -> None:
    """Если MAX не вернул mid — статус считается неотправленным."""
    api = FakeAPI(mid=None)
    ctx = make_context(api)
    assert await ctx.send_status("🎤 …") is None


async def test_update_status_edits_message() -> None:
    """Результат заменяет статусное сообщение (без лишнего сообщения)."""
    api = FakeAPI()
    ctx = make_context(api)

    await ctx.update_status("mid.42", "🎤 Распознано: Потратил 1250")

    assert api.edited == [("mid.42", "🎤 Распознано: Потратил 1250")]
    assert api.sent == [], "не должно быть нового сообщения"


async def test_update_status_noop_without_id() -> None:
    """Без mid ничего не происходит (статус не отправлялся)."""
    api = FakeAPI()
    ctx = make_context(api)
    await ctx.update_status(None, "текст")
    assert api.edited == []


async def test_delete_status_removes_message() -> None:
    """Статус удаляется, если результат не нужен (ошибка распознавания)."""
    api = FakeAPI()
    ctx = make_context(api)

    await ctx.delete_status("mid.42")
    assert api.deleted == ["mid.42"]


async def test_delete_status_noop_without_id() -> None:
    api = FakeAPI()
    ctx = make_context(api)
    await ctx.delete_status(None)
    assert api.deleted == []


async def test_status_methods_survive_api_errors() -> None:
    """Ошибки редактирования/удаления не пробрасываются наружу."""

    class BrokenAPI(FakeAPI):
        async def edit_message(self, message_id: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("edit failed")

        async def delete_message(self, message_id: str) -> dict[str, Any]:
            raise RuntimeError("delete failed")

    ctx = make_context(BrokenAPI())
    await ctx.update_status("mid.1", "текст")  # не должно бросить
    await ctx.delete_status("mid.1")  # не должно бросить
