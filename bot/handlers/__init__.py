"""Модули-сценарии бота.

Импорт этого пакета регистрирует все обработчики в глобальном
:data:`bot.router.router`. Порядок импорта не важен: каждый модуль сам
навешивает декораторы.
"""

from bot.handlers import (
    ai,
    analytics,
    budgets,
    categories,
    export,
    free_text,
    goals,
    history,
    sequence_input,
    settings,
    start,
    subscription,
    transactions,
    voice,
)

# После импорта всех модулей назначаем обработчик по умолчанию.
from bot.handlers.fallback import fallback_handler
from bot.router import router

router.set_fallback(fallback_handler)

__all__ = [
    "ai",
    "analytics",
    "budgets",
    "categories",
    "export",
    "fallback_handler",
    "free_text",
    "goals",
    "history",
    "router",
    "sequence_input",
    "settings",
    "start",
    "subscription",
    "transactions",
    "voice",
]
