"""Подготовка тестового пользователя и демо-данных (локальная отладка).

Создаёт пользователя с известным ``max_user_id``, завершённым онбордингом,
несколькими операциями, бюджетом и целью — чтобы проверить баланс,
статистику и уведомления без ручного ввода.

Запуск::

    python -m scripts.seed_demo --user-id 123456789
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.constants import EXPENSE, INCOME  # noqa: E402
from bot.db import Database  # noqa: E402
from bot.db.users import CategoryRepository, UserRepository  # noqa: E402
from bot.services.budgets import BudgetService  # noqa: E402
from bot.services.goals import GoalService  # noqa: E402
from bot.services.transactions import TransactionService  # noqa: E402
from bot.utils.dates import current_period, today_in_tz  # noqa: E402

DEMO_TRANSACTIONS = (
    (EXPENSE, "Продукты", "1250.00", 0, "Пятёрочка"),
    (EXPENSE, "Транспорт", "320.00", 0, "Такси"),
    (EXPENSE, "Рестораны и кафе", "890.50", 1, "Обед"),
    (EXPENSE, "Продукты", "2100.00", 3, "Закупка на неделю"),
    (EXPENSE, "Жильё", "45000.00", 5, "Аренда"),
    (INCOME, "Зарплата", "120000.00", 5, "Зарплата за месяц"),
    (EXPENSE, "Подписки", "299.00", 7, "Музыка"),
)


async def seed(max_user_id: int) -> int:
    settings = get_settings()
    db = Database(settings.database_url, min_size=1, max_size=3)
    await db.connect()
    try:
        users = UserRepository(db)
        categories = CategoryRepository(db)
        transactions = TransactionService(db)

        user, created = await users.ensure_user(max_user_id, first_name="Тест", username="demo")
        if not user.onboarding_completed:
            await users.complete_onboarding(user.id, "RUB", "Europe/Moscow")
        print(f"Пользователь id={user.id} (max_user_id={user.max_user_id}), создан={created}")

        today = today_in_tz(user.timezone)
        for type_, category_name, amount, days_ago, comment in DEMO_TRANSACTIONS:
            category = await categories.find_by_name(user.id, type_, category_name)
            await transactions.create(
                user_id=user.id,
                type_=type_,
                amount=Decimal(amount),
                currency=user.currency,
                category_id=category.id if category else None,
                transaction_date=today - timedelta(days=days_ago),
                comment=comment,
                source="button",
                raw_text="",
                tz_name=user.timezone,
            )
        print(f"Операций добавлено: {len(DEMO_TRANSACTIONS)}")

        budgets = BudgetService(db)
        await budgets.set_budget(user.id, current_period(user.timezone), Decimal("60000"))
        food = await categories.find_by_name(user.id, EXPENSE, "Продукты")
        if food:
            await budgets.set_budget(
                user.id, current_period(user.timezone), Decimal("8000"), category_id=food.id
            )
        print("Бюджеты: общий 60000 ₽ + Продукты 8000 ₽")

        goals = GoalService(db)
        await goals.create(
            user.id, "Отпуск", Decimal("150000"), deadline=today + timedelta(days=90),
            saved_amount=Decimal("25000"),
        )
        print("Цель: Отпуск 150 000 ₽ (накоплено 25 000 ₽)")
        return user.id
    finally:
        await db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, required=True, help="user_id в MAX")
    args = parser.parse_args()
    internal_id = asyncio.run(seed(args.user_id))
    print(f"Готово. Внутренний id пользователя: {internal_id}")
