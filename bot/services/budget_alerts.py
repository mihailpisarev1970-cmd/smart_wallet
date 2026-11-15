"""Текстовый блок уведомлений о бюджете после записи операции (ТЗ п. 3.9).

Уведомления показываются как продолжение ответа на действие пользователя,
а не отдельной рассылкой. Каждый порог показывается один раз.
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.services.budgets import BudgetService
from bot.services.statistics import StatisticsService
from bot.utils.dates import current_period
from bot.utils.money import format_money
from bot.utils.ui.text import escape_html, progress_bar

logger = logging.getLogger(__name__)


async def append_budget_alerts(ctx: Context, record: object) -> str:
    """Вернуть текст уведомлений о бюджете (пустая строка, если их нет)."""
    if getattr(record, "type", "") != "expense":
        return ""
    if not ctx.user.notifications_enabled:
        return ""

    period = current_period(ctx.user.timezone)
    service = BudgetService(ctx.db)
    try:
        alerts = await service.check_thresholds(
            ctx.user.id, period, category_id=getattr(record, "category_id", None)
        )
    except Exception as exc:
        logger.warning("Не удалось проверить пороги бюджета: %s", exc)
        return ""
    if not alerts:
        return ""

    lines: list[str] = []
    for alert in sorted(alerts, key=lambda item: item.threshold):
        bar = progress_bar(alert.percent)
        if alert.threshold >= 100:
            header = f"🔴 <b>Бюджет «{escape_html(alert.title)}» исчерпан!</b>"
        elif alert.threshold >= 80:
            header = f"🟠 <b>Бюджет «{escape_html(alert.title)}»: {alert.threshold}%</b>"
        else:
            header = f"🟡 Бюджет «{escape_html(alert.title)}»: {alert.threshold}%"
        lines.append(
            f"{header}\n"
            f"<code>{bar}</code>\n"
            f"Потрачено {format_money(alert.spent, currency=ctx.user.currency)} "
            f"из {format_money(alert.amount, currency=ctx.user.currency)}"
        )
        if alert.threshold >= 100:
            stats = StatisticsService(ctx.db)
            from bot.utils.dates import month_range

            totals = await stats.totals(ctx.user.id, month_range(ctx.user.timezone))
            lines.append(
                f"Остаток на месяц: {format_money(totals.income - totals.expense, currency=ctx.user.currency)}"
            )

    await service.mark_alerts_sent(alerts)
    return "\n\n" + "\n\n".join(lines)
