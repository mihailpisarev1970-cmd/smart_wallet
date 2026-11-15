"""Утилиты отображения: кнопки, клавиатуры, экраны, форматирование текста.

Модуль собирает JSON для MAX Bot API в одном месте, чтобы обработчики
не занимались низкоуровневой структурой ``attachments``.
"""

from bot.utils.ui.keyboards import (
    Button,
    Keyboard,
    callback_button,
    link_button,
    message_button,
    payload,
)
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import (
    bold,
    escape_html,
    format_date_ru,
    format_period_ru,
    progress_bar,
)

__all__ = [
    "Button",
    "Keyboard",
    "ScreenView",
    "bold",
    "callback_button",
    "escape_html",
    "format_date_ru",
    "format_period_ru",
    "link_button",
    "message_button",
    "payload",
    "progress_bar",
]
