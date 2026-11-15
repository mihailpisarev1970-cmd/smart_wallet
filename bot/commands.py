"""Команды бота в MAX и их регистрация через ``PATCH /me/commands``.

MAX показывает команды в подсказках при вводе «/» в диалоге с ботом
(iOS, Android, десктоп). Это решает проблему «пустого» экрана
«Хотите продолжить чат с ботом?»: пользователь сразу видит кнопку
``/start`` и понимает, что делать.

Регистрация выполняется один раз при старте приложения
(:func:`register_commands`) и не падает, если платформа недоступна —
команды остаются доступными в текстовом виде.
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)


class BotCommands:
    """Текстовые команды, которые понимает бот."""

    START: Final[str] = "/start"
    MENU: Final[str] = "/menu"
    BALANCE: Final[str] = "/balance"
    HELP: Final[str] = "/help"
    ADD_EXPENSE: Final[str] = "/expense"
    ADD_INCOME: Final[str] = "/income"
    HISTORY: Final[str] = "/history"
    STATS: Final[str] = "/stats"
    BUDGET: Final[str] = "/budget"
    GOALS: Final[str] = "/goals"
    SETTINGS: Final[str] = "/settings"


#: Описания для справки и подсказок.
COMMAND_DESCRIPTIONS: Final[dict[str, str]] = {
    BotCommands.START: "Начать работу / вернуться в меню",
    BotCommands.MENU: "Главное меню",
    BotCommands.BALANCE: "Показать текущий баланс",
    BotCommands.ADD_EXPENSE: "Добавить расход",
    BotCommands.ADD_INCOME: "Добавить доход",
    BotCommands.HISTORY: "История операций",
    BotCommands.STATS: "Статистика",
    BotCommands.BUDGET: "Мой бюджет",
    BotCommands.GOALS: "Цели накопления",
    BotCommands.SETTINGS: "Настройки",
    BotCommands.HELP: "Помощь",
}

#: Команды для подсказок MAX — в порядке важности (до 32 штук).
#: Описания короче 128 символов (ограничение платформы).
COMMANDS_FOR_MAX: Final[tuple[dict[str, str], ...]] = (
    {"name": "start", "description": "🏠 Начать работу / главное меню"},
    {"name": "menu", "description": "📋 Главное меню"},
    {"name": "balance", "description": "💰 Показать баланс"},
    {"name": "expense", "description": "💸 Добавить расход"},
    {"name": "income", "description": "💵 Добавить доход"},
    {"name": "history", "description": "🕘 История операций"},
    {"name": "stats", "description": "📊 Статистика"},
    {"name": "budget", "description": "🎯 Мой бюджет"},
    {"name": "goals", "description": "🏦 Цели накопления"},
    {"name": "settings", "description": "⚙️ Настройки"},
    {"name": "help", "description": "❓ Помощь"},
)


async def register_commands(api: object) -> bool:
    """Зарегистрировать команды в MAX (``PATCH /me/commands``).

    Вызывается при старте бота. Ошибки только логируются: если платформа
    недоступна, команды всё равно работают при вводе вручную.
    """
    setter = getattr(api, "set_commands", None)
    if setter is None:
        logger.debug("У клиента MAX нет set_commands — пропускаем регистрацию")
        return False
    try:
        response = await setter(list(COMMANDS_FOR_MAX))
    except Exception as exc:  # сеть, 401, 500 — не повод падать
        logger.warning("Не удалось зарегистрировать команды в MAX: %s", exc)
        return False
    registered = response.get("commands") if isinstance(response, dict) else None
    count = len(registered) if isinstance(registered, list) else 0
    logger.info("Команды в MAX зарегистрированы: %s шт.", count)
    return True
