"""Тесты отправки файлов в MAX (ожидание готовности вложения).

Реальный баг (14.11.2026): экспорт формировал файл и загружал его, но
``POST /messages`` отвечал 400 ``attachment.not.ready`` — MAX ещё не
обработал файл. Пользователь не получал ничего.
"""

from __future__ import annotations

import pytest

from bot.api import MaxAPIError
from bot.services import upload as upload_module
from bot.services.upload import (
    MAX_UPLOAD_READY_ATTEMPTS,
    UploadedFile,
    is_not_ready_error,
    send_with_file,
)


class FakeClient:
    """MAX-клиент: первые ``fail_times`` вызовов падают с заданной ошибкой."""

    def __init__(self, error: MaxAPIError | None = None, fail_times: int = 0) -> None:
        self.error = error
        self.fail_times = fail_times
        self.calls = 0
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times and self.error is not None:
            raise self.error
        self.sent.append(kwargs)
        return {"ok": True}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Не ждём реальные паузы в тестах."""

    async def fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(upload_module.asyncio, "sleep", fake_sleep)


def test_not_ready_detected() -> None:
    exc = MaxAPIError(
        "MAX API: POST /messages → 400. {'code': 'attachment.not.ready', "
        "'message': 'Key: errors.process.attachment.file.not.processed'}"
    )
    assert is_not_ready_error(exc) is True


def test_other_errors_not_retried() -> None:
    exc = MaxAPIError("MAX API: POST /messages → 404. not found")
    assert is_not_ready_error(exc) is False


async def test_send_retries_until_ready() -> None:
    """Первые 3 попытки — attachment.not.ready, четвёртая успешна."""
    error = MaxAPIError("POST /messages → 400. {'code': 'attachment.not.ready'}")
    client = FakeClient(error=error, fail_times=3)
    attach = UploadedFile(token="tok", raw={}).attachment("file.csv")

    await send_with_file(client, attach, text="файл", chat_id=123)

    assert client.calls == 4
    assert len(client.sent) == 1
    assert client.sent[0]["chat_id"] == 123
    assert client.sent[0]["attachments"][0]["payload"]["token"] == "tok"


async def test_send_gives_up_after_max_attempts() -> None:
    """Если файл так и не готов — пробрасываем ошибку, без бесконечных попыток."""
    error = MaxAPIError("POST /messages → 400. {'code': 'attachment.not.ready'}")
    client = FakeClient(error=error, fail_times=999)
    attach = UploadedFile(token="tok", raw={}).attachment("file.csv")

    with pytest.raises(MaxAPIError):
        await send_with_file(client, attach, text="файл", chat_id=123)

    assert client.calls == MAX_UPLOAD_READY_ATTEMPTS


async def test_send_raises_immediately_on_other_errors() -> None:
    """Ошибка не про готовность (404, нет прав) — без повторов."""
    error = MaxAPIError("POST /messages → 404. {'code': 'error.not.found'}")
    client = FakeClient(error=error, fail_times=999)
    attach = UploadedFile(token="tok", raw={}).attachment("file.csv")

    with pytest.raises(MaxAPIError):
        await send_with_file(client, attach, text="файл", chat_id=123)

    assert client.calls == 1


async def test_send_succeeds_first_try() -> None:
    client = FakeClient()
    attach = UploadedFile(token="tok", raw={}).attachment("file.csv")

    await send_with_file(client, attach, text="файл", chat_id=123)

    assert client.calls == 1


def test_attachment_has_name_and_token() -> None:
    attach = UploadedFile(token="abc", raw={}).attachment("wallet_2026-11-14.csv")
    assert attach["type"] == "file"
    assert attach["payload"]["token"] == "abc"
    assert attach["payload"]["name"] == "wallet_2026-11-14.csv"
