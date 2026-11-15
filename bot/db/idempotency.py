"""Защита от повторной обработки событий MAX (идемпотентность).

MAX (особенно при long polling после рестарта) может доставить то же
событие повторно. Каждое событие получает стабильный ``update_id``:

* ``message_created`` / ``message_edited`` → ``mid`` сообщения;
* ``message_callback`` → ``callback_id`` (или ``mid:payload`` как fallback);
* прочие события → ``<update_type>:<timestamp>:<chat_id>:<user_id>``.

Перед обработкой событие «регистрируется» в ``processed_updates`` уникальным
``INSERT ... ON CONFLICT DO NOTHING``: если строка не вставилась — событие уже
обработано.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from bot.db import Database

logger = logging.getLogger(__name__)


def build_update_id(update: dict[str, Any]) -> str:
    """Построить стабильный идентификатор события."""
    update_type = str(update.get("update_type") or "unknown")
    message = update.get("message") or {}

    if update_type in {"message_created", "message_edited"}:
        mid = (message.get("body") or {}).get("mid") or message.get("mid")
        if mid:
            return f"{update_type}:{mid}"

    if update_type == "message_callback":
        callback = update.get("callback") or {}
        callback_id = callback.get("callback_id") or callback.get("id")
        if callback_id:
            return f"{update_type}:{callback_id}"
        mid = (message.get("body") or {}).get("mid") or message.get("mid") or ""
        return f"{update_type}:{mid}:{callback.get('payload', '')}"

    chat_id = update.get("chat_id") or (message.get("recipient") or {}).get("chat_id") or 0
    sender = message.get("sender") or update.get("user") or {}
    user_id = sender.get("user_id") or 0
    return f"{update_type}:{update.get('timestamp', 0)}:{chat_id}:{user_id}"


class IdempotencyGuard:
    """Регистрация обработанных событий в БД."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def is_new(self, update_id: str, update_type: str, user_max_id: int | None) -> bool:
        """``True`` — событие новое и зарезервировано за этим обработчиком."""
        key = self._key(update_id)
        try:
            result = await self._db.execute(
                """
                INSERT INTO processed_updates (update_id, update_type, user_max_id, created_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (update_id) DO NOTHING
                """,
                key,
                update_type[:32],
                user_max_id,
            )
        except Exception as exc:
            logger.warning("Идемпотентность: не удалось записать %s: %s", key, exc)
            return True
        return result.endswith("1")

    @staticmethod
    def _key(update_id: str) -> str:
        """Ключ для ``update_id`` (колонка — varchar(128)).

        ``callback_id`` в MAX достигает ~150 символов, поэтому длинные
        идентификаторы заменяются на ``<первые 80>:<sha256[:32]>``.
        """
        if len(update_id) <= 128:
            return update_id
        digest = hashlib.sha256(update_id.encode("utf-8")).hexdigest()[:32]
        return f"{update_id[:80]}:{digest}"

    async def forget(self, update_id: str) -> None:
        """Снять отметку об обработке (если обработка упала до побочных эффектов)."""
        await self._db.execute(
            "DELETE FROM processed_updates WHERE update_id = $1", self._key(update_id)
        )

    async def cleanup(self, keep_days: int = 14) -> int:
        """Удалить старые записи, чтобы таблица не росла бесконечно."""
        result = await self._db.execute(
            "DELETE FROM processed_updates WHERE created_at < NOW() - ($1 || ' days')::interval",
            str(keep_days),
        )
        deleted = int(result.split()[-1]) if result else 0
        if deleted:
            logger.info("Очищено %s старых записей processed_updates", deleted)
        return deleted
