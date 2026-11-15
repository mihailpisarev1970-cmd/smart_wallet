"""Отправка файлов в MAX через механизм загрузки вложений.

Порядок (см. POST /uploads в документации MAX):

1. ``POST /uploads?type=file`` → ``{"url": "<upload_url>"}``;
2. ``POST <upload_url>`` с multipart-полем ``data: <файл>`` → токен вложения;
3. отправить сообщение с ``attachments: [{"type": "file", "payload": {"token": ...}}]``.

Особенность MAX (выяснено эмпирически, 14.11.2026): после загрузки файл
некоторое время обрабатывается на стороне платформы. Если сразу отправить
сообщение, ``POST /messages`` отвечает::

    400 {"code": "attachment.not.ready",
         "message": "Key: errors.process.attachment.file.not.processed"}

Поэтому сообщение с файлом отправляется с повторами (:func:`send_with_file`):
задержка растёт линейно (0.5 с → 1 с → 1.5 с …), всего до
``MAX_UPLOAD_READY_ATTEMPTS`` попыток. Обычно хватает второй-третьей.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from bot.api import MaxAPIError, MaxClient

logger = logging.getLogger(__name__)

#: Сколько раз пытаться отправить сообщение с только что загруженным файлом.
MAX_UPLOAD_READY_ATTEMPTS = 6

#: Базовая пауза перед повтором, сек (умножается на номер попытки).
UPLOAD_READY_DELAY = 0.5

#: Коды MAX, означающие «файл ещё обрабатывается» (можно повторить).
_NOT_READY_CODES = ("attachment.not.ready", "not.processed")


@dataclass(slots=True)
class UploadedFile:
    """Результат загрузки файла."""

    token: str
    raw: dict[str, Any]

    def attachment(self, name: str) -> dict[str, Any]:
        """Вложение типа ``file`` для ``POST /messages``."""
        return {"type": "file", "payload": {"token": self.token, "name": name[:255]}}


def is_not_ready_error(exc: BaseException) -> bool:
    """Это ошибка «вложение ещё не обработано»? Тогда имеет смысл повторить."""
    text = str(exc)
    return any(code in text for code in _NOT_READY_CODES)


async def upload_file(
    client: MaxClient,
    content: bytes,
    filename: str,
    *,
    upload_type: str = "file",
) -> UploadedFile:
    """Загрузить файл в MAX и вернуть токен вложения."""
    info = await client.get_upload_url(upload_type)
    upload_url = info.get("url") or info.get("upload_url")
    if not upload_url:
        raise MaxAPIError(f"MAX не вернул URL для загрузки: {info}")

    payload = await client.post_to_upload_url(str(upload_url), content, filename)
    token = (
        payload.get("token")
        or payload.get("fileId")
        or payload.get("file_id")
        or (payload.get("retval") or {}).get("token")
    )
    if not token:
        raise MaxAPIError(f"MAX не вернул токен файла: {payload}")
    return UploadedFile(token=str(token), raw=payload)


async def wait_until_ready(client: MaxClient, attachment: dict[str, Any]) -> bool:
    """Подождать, пока платформа обработает вложение.

    Проверяем повторной отправкой «пустого» пробного сообщения нельзя —
    это спамит пользователя. Поэтому просто выдерживаем паузу, достаточную
    для обработки файла (~1–2 с), и возвращаем ``True``. Реальная проверка
    происходит в :func:`send_with_file`.
    """
    await asyncio.sleep(UPLOAD_READY_DELAY)
    return True


async def send_with_file(
    client: MaxClient,
    attach: dict[str, Any],
    *,
    text: str = "",
    chat_id: int | None = None,
    user_id: int | None = None,
    max_attempts: int = MAX_UPLOAD_READY_ATTEMPTS,
) -> dict[str, Any]:
    """Отправить сообщение с файлом, дожидаясь обработки вложения.

    Повторяем только при ``attachment.not.ready`` — остальные ошибки
    (нет прав, неверный chat_id) пробрасываем сразу, повторы не помогут.
    """
    last_error: MaxAPIError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await client.send_message(
                text=text, attachments=[attach], chat_id=chat_id, user_id=user_id
            )
        except MaxAPIError as exc:
            if not is_not_ready_error(exc):
                raise
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = UPLOAD_READY_DELAY * attempt
            logger.info(
                "Файл ещё обрабатывается MAX (попытка %s/%s), ждём %.1f с",
                attempt,
                max_attempts,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_error or MaxAPIError("Не удалось отправить файл: вложение не готово")

