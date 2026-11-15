"""Экран бота: текст + клавиатура + новое состояние диалога.

Обработчик возвращает один или несколько ``ScreenView``; диспетчер сам
отправляет сообщения в MAX и сохраняет состояние в БД.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard


@dataclass(slots=True)
class ScreenView:
    """Описание ответа бота пользователю."""

    text: str
    keyboard: Keyboard = field(default_factory=Keyboard)
    #: Следующий экран. ``None`` — состояние не меняется.
    next_screen: Screen | None = None
    #: Данные, которые нужно сохранить в состояние вместе с экраном.
    state_data: dict[str, Any] | None = None
    #: Полностью заменить данные состояния (по умолчанию — обновить).
    reset_data: bool = False
    #: Отправлять как HTML (по умолчанию да, удобно для разметки).
    parse_mode: str = "html"
    #: Уведомление-«тост» для callback-ответа.
    toast: str | None = None
    #: Дополнительные вложения (например, файл экспорта).
    attachments: list[dict[str, Any]] = field(default_factory=list)

    def with_state(self, screen: Screen, **data: Any) -> ScreenView:
        """Удобная установка нового экрана и данных."""
        self.next_screen = screen
        self.state_data = data or self.state_data
        return self

    def replace_state(self, screen: Screen, **data: Any) -> ScreenView:
        """Перейти на экран, полностью заменив данные состояния."""
        self.next_screen = screen
        self.state_data = data
        self.reset_data = True
        return self


class TextScreen(ScreenView):
    """Простое текстовое сообщение без перехода состояния."""
