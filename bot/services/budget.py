"""Алиас для сервиса бюджетов.

Логика лежит в :mod:`bot.services.budgets`; здесь — обратная совместимость
импорта ``bot.services.budget``. Сохранение ради читаемости импортов в
обработчиках.
"""

from bot.services.budgets import (
    BudgetAlert,
    BudgetRecord,
    BudgetService,
    BudgetStatus,
)

__all__ = ["BudgetAlert", "BudgetRecord", "BudgetService", "BudgetStatus"]
