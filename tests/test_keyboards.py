"""Тесты клавиатур и экранов (ограничения MAX Bot API)."""

from __future__ import annotations

from bot.utils.ui.keyboards import (
    MAX_BUTTONS,
    Button,
    Keyboard,
    callback_button,
    link_button,
    payload,
)
from bot.utils.ui.menu import main_menu_keyboard
from bot.utils.ui.text import escape_html, format_date_ru, plural_ru, progress_bar


def test_callback_button_payload_encoding() -> None:
    button = callback_button("Текст", "tx:cat", "42")
    assert button.to_dict() == {"type": "callback", "text": "Текст", "payload": "tx:cat:42"}


def test_payload_escapes_colons_in_args() -> None:
    assert payload("ai:save", "a:b") == "ai:save:a|b"


def test_link_button_requires_url() -> None:
    button = link_button("Сайт", "https://example.com")
    assert button.to_dict()["url"] == "https://example.com"
    assert "payload" not in button.to_dict()


def test_button_text_is_truncated_to_platform_limit() -> None:
    button = Button(text="я" * 200, type="callback", payload="x")
    assert len(button.to_dict()["text"]) == 128


def test_keyboard_to_attachments_structure() -> None:
    keyboard = Keyboard().row(callback_button("A", "a"), callback_button("B", "b"))
    attachments = keyboard.to_attachments()
    assert attachments[0]["type"] == "inline_keyboard"
    buttons = attachments[0]["payload"]["buttons"]
    assert [btn["payload"] for btn in buttons[0]] == ["a", "b"]


def test_empty_keyboard_produces_no_attachments() -> None:
    assert Keyboard().to_attachments() == []


def test_keyboard_respects_max_buttons() -> None:
    keyboard = Keyboard()
    keyboard.add(*[callback_button(f"b{i}", "a", str(i)) for i in range(MAX_BUTTONS + 20)])
    attachments = keyboard.to_attachments()
    total = sum(len(row) for row in attachments[0]["payload"]["buttons"])
    assert total <= MAX_BUTTONS


def test_main_menu_has_required_sections() -> None:
    """Главное меню должно содержать все разделы из ТЗ п. 3.2."""
    keyboard = main_menu_keyboard()
    actions = {button.payload.split(":")[0] for row in keyboard.rows for button in row}
    expected = {
        "tx",       # добавить доход / расход
        "balance",
        "history",
        "stats",
        "budget",
        "goals",
        "ai",
        "settings",
        "help",
        "about",
    }
    assert expected.issubset(actions)


def test_escape_html() -> None:
    assert escape_html("<b>&") == "&lt;b&gt;&amp;"


def test_format_date_ru() -> None:
    from datetime import date

    assert format_date_ru(date(2026, 11, 6)) == "6 ноября 2026"
    assert format_date_ru(date(2026, 11, 6), short=True) == "06.11.2026"


def test_progress_bar_bounds() -> None:
    assert progress_bar(0).endswith("0%")
    assert progress_bar(150).endswith("100%")
    assert "█" in progress_bar(50)


def test_plural_ru() -> None:
    assert plural_ru(1, "операция", "операции", "операций") == "операция"
    assert plural_ru(3, "операция", "операции", "операций") == "операции"
    assert plural_ru(11, "операция", "операции", "операций") == "операций"
    assert plural_ru(21, "операция", "операции", "операций") == "операция"
