"""Long polling как канал получения событий MAX (для локальной разработки).

Документация MAX: ``GET /updates`` с параметрами ``limit``, ``timeout``
(0..90 секунд), ``marker``. Ответ содержит ``updates`` и ``marker`` —
указатель на следующее ожидаемое обновление.

Long polling не предназначен для production (ограничен по скорости и сроку
хранения событий) — на сервере используется webhook.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from bot.api import MaxAPIError, MaxAuthError, MaxClient

logger = logging.getLogger(__name__)

#: Пауза при ошибке, чтобы не спамить API.
ERROR_BACKOFF_SECONDS = 3.0
#: Максимальная пауза при повторяющихся ошибках.
MAX_BACKOFF_SECONDS = 60.0


async def poll_updates(
    client: MaxClient,
    on_update: UpdateHandler,
    *,
    timeout: int = 30,
    limit: int = 100,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Бесконечно получать события и передавать их обработчику.

    ``marker`` сохраняется в памяти процесса: после перезапуска бот начнёт с
    последнего события. Идемпотентность обработки страхует от повторов.
    """
    marker: int | None = None
    backoff = ERROR_BACKOFF_SECONDS
    stop_event = stop_event or asyncio.Event()

    while not stop_event.is_set():
        try:
            batch: dict[str, Any] = await client.get_updates(
                marker=marker, timeout=timeout, limit=limit
            )
        except MaxAuthError:
            logger.critical("Неверный токен бота — long polling остановлен")
            raise
        except MaxAPIError as exc:
            logger.warning("Ошибка получения событий: %s (пауза %.0f с)", exc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
            continue

        backoff = ERROR_BACKOFF_SECONDS
        new_marker = batch.get("marker")
        if new_marker is not None:
            marker = new_marker

        for update in batch.get("updates") or []:
            if stop_event.is_set():
                break
            await on_update(update)


class UpdateHandler:  # pragma: no cover - протокол для аннотации
    """Протокол обработчика событий."""

    async def __call__(self, update: dict[str, Any]) -> None: ...
