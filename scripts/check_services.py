"""Проверка расчётов на реальных данных: баланс, статистика, бюджеты, цели.

Запуск::

    python -m scripts.check_services --max-user-id 999000111

Результат пишется в ``.report/services.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.db import Database  # noqa: E402
from bot.db.users import UserRepository  # noqa: E402
from bot.services.budgets import BudgetService  # noqa: E402
from bot.services.export import ExportService  # noqa: E402
from bot.services.goals import GoalService  # noqa: E402
from bot.services.statistics import StatisticsService  # noqa: E402
from bot.services.transactions import TransactionService  # noqa: E402
from bot.utils.dates import current_period, month_range, today_range  # noqa: E402
from bot.utils.money import format_money  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "services.txt"


async def main(max_user_id: int) -> int:
    settings = get_settings()
    db = Database(settings.database_url, min_size=1, max_size=3)
    await db.connect()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")

    try:
        users = UserRepository(db)
        user = await users.get_by_max_id(max_user_id)
        if user is None:
            log(f"Пользователь {max_user_id} не найден")
            return 1
        currency = user.currency
        log(f"Пользователь: {user.id} (max {user.max_user_id}), {currency}, {user.timezone}")

        stats = StatisticsService(db)
        lifetime = await stats.lifetime_totals(user.id)
        month = await stats.totals(user.id, month_range(user.timezone))
        today = await stats.totals(user.id, today_range(user.timezone))
        log(f"За всё время: доходы {format_money(lifetime.income, currency=currency)}, "
            f"расходы {format_money(lifetime.expense, currency=currency)}, "
            f"баланс {format_money(lifetime.balance, currency=currency)}")
        log(f"Месяц: доходы {format_money(month.income, currency=currency)}, "
            f"расходы {format_money(month.expense, currency=currency)}")
        log(f"Сегодня: расходы {format_money(today.expense, currency=currency)}")

        data = await stats.build(user.id, month_range(user.timezone), tz_name=user.timezone)
        log("\nСтатистика по категориям:")
        for item in data.by_category:
            log(f"  {item.name:24} {format_money(item.total, currency=currency):>12} "
                f"{item.share:5.1f}% ({item.count})")
        log(f"  Топ-категория: {data.top_category.name if data.top_category else '—'}")
        log(f"  Средний расход в день: {format_money(data.avg_per_day, currency=currency)}")
        log("  Динамика по месяцам: " + ", ".join(
            f"{point.period}: {format_money(point.expense, with_currency=False)}"
            for point in data.monthly
        ))

        budgets = await BudgetService(db).status(user.id, current_period(user.timezone))
        log("\nБюджеты:")
        if budgets.overall:
            log(f"  Общий: {format_money(budgets.overall.spent, currency=currency)} "
                f"из {format_money(budgets.overall.amount, currency=currency)} "
                f"({budgets.overall.percent:.0f}%)")
        for record in budgets.categories:
            log(f"  {record.title}: {format_money(record.spent, currency=currency)} "
                f"из {format_money(record.amount, currency=currency)} ({record.percent:.0f}%)")

        alerts = await BudgetService(db).check_thresholds(
            user.id, current_period(user.timezone)
        )
        log("  Пороговые уведомления: " + (", ".join(
            f"{a.title} >= {a.threshold}%" for a in alerts
        ) or "нет"))

        goals = await GoalService(db).list(user.id)
        log("\nЦели:")
        for goal in goals:
            log(f"  {goal.name}: {format_money(goal.saved_amount, currency=currency)} / "
                f"{format_money(goal.target_amount, currency=currency)} ({goal.percent:.0f}%)")

        export = ExportService(db)
        csv_bytes, csv_count = await export.to_csv(user.id)
        xlsx_bytes, xlsx_count = await export.to_excel(user.id)
        log(f"\nЭкспорт CSV: {csv_count} строк, {len(csv_bytes)} байт")
        log(f"Экспорт Excel: {xlsx_count} строк, {len(xlsx_bytes)} байт")

        transactions = TransactionService(db)
        records = await transactions.list_period(
            user.id, month_range(user.timezone), limit=5
        )
        log("\nПоследние операции:")
        for record in records:
            log(f"  #{record.id} {record.type_label}: {record.sign_symbol}"
                f"{format_money(record.amount, currency=currency)} — {record.category_name}")
        return 0
    finally:
        await db.close()
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")
        print(out.getvalue())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-user-id", type=int, required=True)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.max_user_id)))
