"""Контекст обработки одного события (передаётся в обработчики).

Содержит всё, что нужно сценарию: пользователя из БД, текущее состояние
диалога, текст сообщения, распознанное действие и доступ к зависимостям
(репозитории, API-клиент, настройки).
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bot.api import MaxClient
    from bot.config import Settings
    from bot.db import Database
    from bot.db.states import DialogState, StateRepository
    from bot.db.users import CategoryRepository, UserRecord, UserRepository


@dataclass(slots=True)
class Context:
    """Всё, что нужно обработчику для ответа пользователю."""

    #: ``user_id`` пользователя MAX (не путать с ``users.id``).
    max_user_id: int
    user: UserRecord
    state: DialogState
    db: Database
    api: MaxClient
    settings: Settings
    users: UserRepository
    categories: CategoryRepository
    states: StateRepository
    #: Тип события: ``message`` | ``callback`` | ``command`` | ``voice`` | ``system``
    event: str = "message"
    #: Текст сообщения или подпись нажатой кнопки.
    text: str = ""
    #: ID чата MAX (для диалога совпадает с user_id, но не всегда).
    chat_id: int | None = None
    #: ``mid`` сообщения пользователя (для ответа/редактирования).
    message_id: str | None = None
    #: ``callback_id`` для ответа на нажатие кнопки.
    callback_id: str | None = None
    #: Аргументы callback-payload (после первого двоеточия).
    args: list[str] = field(default_factory=list)
    #: Вложения сообщения (для голосовых и файлов).
    attachments: list[dict[str, Any]] = field(default_factory=list)
    #: Сырое событие MAX (для отладки и особых случаев).
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def arg(self) -> str:
        """Первый аргумент callback-payload."""
        return self.args[0] if self.args else ""

    def arg_int(self, index: int = 0) -> int | None:
        """Аргумент payload как целое число."""
        try:
            return int(self.args[index])
        except (IndexError, TypeError, ValueError):
            return None

    # --- статусные сообщения (долгие операции) ---------------------------

    async def send_status(self, text: str) -> str | None:
        """Отправить промежуточное сообщение («🎤 Распознаю…»).

        Возвращает ``mid`` отправленного сообщения — его потом можно
        заменить результатом через :meth:`update_status`. ``None`` — если
        отправить не удалось (тогда просто не показываем статус).
        """
        try:
            response = await self.api.send_message(
                user_id=self.max_user_id, text=text, format="html"
            )
        except Exception:
            return None

        body = response.get("body") if isinstance(response, dict) else None
        if isinstance(body, dict):
            return body.get("mid")
        return response.get("mid") if isinstance(response, dict) else None

    async def update_status(self, message_id: str | None, text: str) -> None:
        """Заменить текст статусного сообщения результатом."""
        if not message_id:
            return
        with contextlib.suppress(Exception):
            await self.api.edit_message(message_id, text=text, format="html")

    async def delete_status(self, message_id: str | None) -> None:
        """Удалить статусное сообщение (если результат не нужен)."""
        if not message_id:
            return
        with contextlib.suppress(Exception):
            await self.api.delete_message(message_id)
