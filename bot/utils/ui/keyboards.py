"""Сборка кнопок и клавиатур для MAX Bot API.

Структура (см. https://dev.max.ru/docs-api, объект ``Keyboard``)::

    {
      "type": "inline_keyboard",
      "payload": {
        "buttons": [
          [{"type": "callback", "text": "Текст", "payload": "action:arg"}],
          [{"type": "link", "text": "Сайт", "url": "https://..."}]
        ]
      }
    }

Ограничения платформы: ``text`` — до 128 символов, ``payload`` — до 1024,
``url`` — до 2048. Рекомендуется: 20 символов при 1 кнопке в ряду, 10 — при 2,
5 — при 3. Кнопок в сообщении — не больше 210.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ButtonType = Literal["callback", "link", "message"]

MAX_BUTTON_TEXT = 128
MAX_PAYLOAD = 1024
MAX_URL = 2048
#: Платформенное ограничение MAX на количество кнопок в одном сообщении.
MAX_BUTTONS = 210


@dataclass(frozen=True, slots=True)
class Button:
    """Кнопка сообщения."""

    text: str
    type: ButtonType = "callback"
    payload: str | None = None
    url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"type": self.type, "text": self.text[:MAX_BUTTON_TEXT]}
        if self.type == "callback" and self.payload is not None:
            data["payload"] = self.payload[:MAX_PAYLOAD]
        if self.type == "link" and self.url:
            data["url"] = self.url[:MAX_URL]
        return data


def callback_button(text: str, action: str, *args: str) -> Button:
    """Кнопка ``callback``: payload кодируется как ``action:arg1:arg2``."""
    return Button(text=text, type="callback", payload=payload(action, *args))


def message_button(text: str) -> Button:
    """Кнопка, отправляющая свой текст как обычное сообщение."""
    return Button(text=text, type="message")


def link_button(text: str, url: str) -> Button:
    """Кнопка-ссылка."""
    return Button(text=text, type="link", url=url)


def payload(action: str, *args: str) -> str:
    """Собрать payload кнопки: ``action:arg1:arg2``.

    Двоеточия внутри аргументов заменяются на ``|``, чтобы разбор был
    однозначным (см. :func:`parse_payload` в роутере).
    """
    safe_args = [str(arg).replace(":", "|") for arg in args]
    return ":".join([action, *safe_args])


@dataclass(slots=True)
class Keyboard:
    """Inline-клавиатура: двумерный массив кнопок."""

    rows: list[list[Button]] = field(default_factory=list)

    def row(self, *buttons: Button) -> Keyboard:
        if buttons:
            self.rows.append(list(buttons))
        return self

    def add(self, *buttons: Button, per_row: int = 2) -> Keyboard:
        """Добавить кнопки, разбивая их на ряды по ``per_row``."""
        chunk: list[Button] = []
        for button in buttons:
            chunk.append(button)
            if len(chunk) == per_row:
                self.rows.append(chunk)
                chunk = []
        if chunk:
            self.rows.append(chunk)
        return self

    def back(self, action: str = "menu:main", text: str = "« Назад") -> Keyboard:
        """Добавить ряд с кнопкой возврата."""
        self.rows.append([callback_button(text, action)])
        return self

    @property
    def is_empty(self) -> bool:
        return not any(self.rows)

    def to_attachments(self) -> list[dict[str, Any]]:
        """Преобразовать в ``attachments`` для POST /messages."""
        if self.is_empty:
            return []
        flat = [button for row in self.rows for button in row]
        if len(flat) > MAX_BUTTONS:
            flat = flat[:MAX_BUTTONS]
            rows: list[list[Button]] = []
            for index in range(0, len(flat), 2):
                rows.append(flat[index : index + 2])
        else:
            rows = [row for row in self.rows if row]
        return [
            {
                "type": "inline_keyboard",
                "payload": {"buttons": [[button.to_dict() for button in row] for row in rows]},
            }
        ]
