"""Тесты регистрации команд бота в MAX (``PATCH /me/commands``).

Проблема (14.11.2026): при заходе в бота MAX показывал пустой экран
«Хотите продолжить чат с ботом?» без единой подсказки. Метод
``PATCH /me/commands`` существует и работает, регистрируем команды при старте.
"""

from __future__ import annotations

import pytest

from bot.commands import COMMAND_DESCRIPTIONS, COMMANDS_FOR_MAX, BotCommands, register_commands

# --- содержимое команд ----------------------------------------------------


def test_commands_within_platform_limits() -> None:
    """MAX: до 32 команд, name 1–64, description 1–128."""
    assert 1 <= len(COMMANDS_FOR_MAX) <= 32
    for item in COMMANDS_FOR_MAX:
        assert 1 <= len(item["name"]) <= 64
        assert 1 <= len(item["description"]) <= 128


def test_start_command_is_first() -> None:
    """«/start» должен быть первым — это главная точка входа."""
    assert COMMANDS_FOR_MAX[0]["name"] == "start"


def test_command_names_have_no_slash() -> None:
    """В PATCH /me/commands имя передаётся без слэша."""
    for item in COMMANDS_FOR_MAX:
        assert not item["name"].startswith("/")


def test_all_commands_have_descriptions() -> None:
    """Каждая команда с подсказкой должна иметь описание."""
    for item in COMMANDS_FOR_MAX:
        assert item["description"].strip()


def test_command_descriptions_cover_all_constants() -> None:
    """Все константы BotCommands описаны в справке."""
    constants = {
        value
        for name, value in vars(BotCommands).items()
        if not name.startswith("_") and isinstance(value, str)
    }
    assert constants.issubset(COMMAND_DESCRIPTIONS.keys())


def test_no_duplicate_command_names() -> None:
    names = [item["name"] for item in COMMANDS_FOR_MAX]
    assert len(names) == len(set(names))


# --- регистрация ----------------------------------------------------------


class FakeApi:
    """Клиент MAX, запоминающий вызов set_commands."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[list[dict[str, str]]] = []

    async def set_commands(self, commands: list[dict[str, str]]) -> dict:
        if self.error is not None:
            raise self.error
        self.sent.append(commands)
        return {"commands": commands}


class ApiWithoutCommands:
    """Клиент без метода set_commands (старая версия)."""


async def test_register_sends_commands() -> None:
    api = FakeApi()
    assert await register_commands(api) is True
    assert len(api.sent) == 1
    assert api.sent[0][0]["name"] == "start"


async def test_register_swallows_errors() -> None:
    """Ошибка сети/401 не должна ронять запуск бота."""
    api = FakeApi(error=RuntimeError("MAX недоступен"))
    assert await register_commands(api) is False


async def test_register_without_method() -> None:
    """У клиента нет set_commands — просто пропускаем."""
    assert await register_commands(ApiWithoutCommands()) is False


@pytest.mark.parametrize("name", ["start", "menu", "help", "balance"])
async def test_key_commands_registered(name: str) -> None:
    api = FakeApi()
    await register_commands(api)
    names = [item["name"] for item in api.sent[0]]
    assert name in names
