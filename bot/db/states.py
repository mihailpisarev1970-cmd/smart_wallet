"""Хранилище состояний диалога (FSM) в PostgreSQL.

Состояние — это ``screen`` (см. :mod:`bot.states`) плюс произвольные данные
черновика (сумма, выбранная категория и т.п.). Хранение в БД позволяет
продолжить диалог после перезапуска бота и корректно работать в несколько
процессов.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from bot.db import Database
from bot.states import Screen

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DialogState:
    """Текущий экран и данные черновика."""

    screen: Screen = Screen.MAIN_MENU
    data: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def int(self, key: str) -> int | None:
        value = self.data.get(key)
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class StateRepository:
    """Чтение и запись ``user_states`` (ключ — внутренний ``user_id`` БД)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get(self, user_id: int) -> DialogState:
        row = await self._db.fetchrow(
            "SELECT screen, data FROM user_states WHERE user_id = $1", user_id
        )
        if not row:
            return DialogState()
        raw_screen = row["screen"] or Screen.MAIN_MENU.value
        try:
            screen = Screen(raw_screen)
        except ValueError:
            logger.warning("Неизвестный экран в БД: %s — сбрасываю на главное меню", raw_screen)
            screen = Screen.MAIN_MENU
        data = row["data"]
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError:
                data = {}
        return DialogState(screen=screen, data=dict(data or {}))

    async def set(
        self,
        user_id: int,
        screen: Screen,
        data: dict[str, Any] | None = None,
        *,
        replace: bool = True,
    ) -> None:
        """Сохранить состояние. ``replace=False`` — объединить с текущим."""
        if replace or data is None:
            payload = data or {}
        else:
            current = await self.get(user_id)
            payload = {**current.data, **data}
        await self._db.execute(
            """
            INSERT INTO user_states (user_id, screen, data, updated_at)
            VALUES ($1, $2, $3::jsonb, NOW())
            ON CONFLICT (user_id)
            DO UPDATE SET screen = EXCLUDED.screen, data = EXCLUDED.data, updated_at = NOW()
            """,
            user_id,
            str(screen),
            json.dumps(payload, ensure_ascii=False, default=str),
        )

    async def reset(self, user_id: int) -> None:
        """Вернуть пользователя в главное меню и очистить черновик."""
        await self.set(user_id, Screen.MAIN_MENU, {})
