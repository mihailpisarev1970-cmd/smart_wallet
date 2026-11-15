"""Баланс и статистика (ТЗ п. 3.6, 3.8) — расчёты только программные.

Экраны:
* «Мой баланс» — доходы/расходы за всё время и за текущий месяц;
* «Статистика» — расходы по категориям, топ-категория, динамика по месяцам,
  сравнение с предыдущим месяцем, средний расход в день.
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.services.statistics import StatisticsService
from bot.states import Screen
from bot.utils.dates import month_range, today_range, week_range
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import (
    escape_html,
    format_amount,
    format_period_ru,
    progress_bar,
)

logger = logging.getLogger(__name__)


@router.callback("balance:show")
@router.command("/balance")
async def balance_screen(ctx: Context) -> ScreenView:
    """Экран баланса (ТЗ п. 3.6)."""
    stats = StatisticsService(ctx.db)
    lifetime = await stats.lifetime_totals(ctx.user.id)
    month = await stats.totals(ctx.user.id, month_range(ctx.user.timezone))
    today = await stats.totals(ctx.user.id, today_range(ctx.user.timezone))
    week = await stats.totals(ctx.user.id, week_range(ctx.user.timezone))
    currency = ctx.user.currency

    text = (
        "<b>📊 Мой баланс</b>\n\n"
        f"Текущий баланс: <b>{escape_html(format_money(lifetime.balance, currency=currency))}</b>\n"
        f"Всего доходов: {escape_html(format_money(lifetime.income, currency=currency))}\n"
        f"Всего расходов: {escape_html(format_money(lifetime.expense, currency=currency))}\n\n"
        "<b>За текущий месяц</b>\n"
        f"Доходы: {escape_html(format_money(month.income, currency=currency))}\n"
        f"Расходы: {escape_html(format_money(month.expense, currency=currency))}\n"
        f"Итого: <b>{escape_html(format_money(month.balance, currency=currency))}</b>\n\n"
        "<b>Коротко</b>\n"
        f"Сегодня: −{escape_html(format_money(today.expense, currency=currency))}, "
        f"+{escape_html(format_money(today.income, currency=currency))}\n"
        f"7 дней: −{escape_html(format_money(week.expense, currency=currency))}, "
        f"+{escape_html(format_money(week.income, currency=currency))}"
    )
    if lifetime.income == 0 and lifetime.expense == 0:
        text += (
            "\n\n<i>Пока нет операций. Добавьте первый расход — баланс обновится сразу.</i>"
        )

    keyboard = Keyboard().row(
        callback_button("📈 Статистика", "stats:open"),
        callback_button("🕘 История", "history:open"),
    )
    keyboard.row(
        callback_button("💸 Добавить расход", "tx:new", "expense"),
        callback_button("💰 Добавить доход", "tx:new", "income"),
    )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.MAIN_MENU
    view.state_data = {}
    return view


@router.callback("stats:open")
@router.command("/stats")
async def stats_open(ctx: Context) -> ScreenView:
    """Меню статистики: за какой период считать."""
    keyboard = Keyboard().row(
        callback_button("Сегодня", "stats:show", "today"),
        callback_button("7 дней", "stats:show", "week"),
    )
    keyboard.row(
        callback_button("Текущий месяц", "stats:show", "month"),
        callback_button("3 месяца", "stats:show", "quarter"),
    )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    view = ScreenView(
        text="<b>📈 Статистика</b>\n\nВыберите период:",
        keyboard=keyboard,
    )
    view.next_screen = Screen.STATS_MENU
    return view


def _range_for_key(ctx: Context, key: str):
    from datetime import date, timedelta

    from bot.utils.dates import custom_range

    if key == "today":
        return today_range(ctx.user.timezone)
    if key == "week":
        return week_range(ctx.user.timezone)
    if key == "quarter":
        today = date.today()
        return custom_range(today.replace(day=1) - timedelta(days=62), today)
    return month_range(ctx.user.timezone)


@router.callback("stats:show")
async def stats_show(ctx: Context) -> ScreenView:
    """Подробная статистика за период (ТЗ п. 3.8)."""
    key = ctx.arg or "month"
    date_range = _range_for_key(ctx, key)
    service = StatisticsService(ctx.db)
    data = await service.build(ctx.user.id, date_range, tz_name=ctx.user.timezone)
    currency = ctx.user.currency

    lines = [
        f"<b>📈 Статистика: {escape_html(data.range_label)}</b>",
        "",
        f"Доходы: {escape_html(format_money(data.totals.income, currency=currency))}",
        f"Расходы: {escape_html(format_money(data.totals.expense, currency=currency))}",
        f"Разница: <b>{escape_html(format_money(data.totals.balance, currency=currency))}</b>",
    ]

    if data.by_category:
        lines.append("")
        lines.append("<b>Расходы по категориям</b>")
        for item in data.by_category[:8]:
            lines.append(
                f"• {escape_html(item.name)} — "
                f"{escape_html(format_money(item.total, currency=currency))} "
                f"({item.share:.0f}%, {item.count} шт.)"
            )
        if data.top_category:
            lines.append("")
            lines.append(
                f"Самая затратная: <b>{escape_html(data.top_category.name)}</b> — "
                f"{escape_html(format_money(data.top_category.total, currency=currency))}"
            )
        if data.avg_per_day > 0:
            lines.append(f"В среднем в день: {escape_html(format_money(data.avg_per_day, currency=currency))}")
    else:
        lines.append("")
        lines.append("За период расходов нет.")

    # Сравнение с предыдущим месяцем (для «месячных» отчётов).
    if data.previous_month.expense or data.previous_month.income:
        diff = data.current_month.expense - data.previous_month.expense
        arrow = "▲" if diff > 0 else ("▼" if diff < 0 else "=")
        lines.append("")
        lines.append("<b>Сравнение с прошлым месяцем</b>")
        lines.append(
            f"Расходы: {escape_html(format_money(data.current_month.expense, currency=currency))} "
            f"{arrow} {escape_html(format_money(abs(diff), currency=currency))}"
        )
        lines.append(
            f"Прошлый месяц: {escape_html(format_money(data.previous_month.expense, currency=currency))}"
        )

    # Динамика по месяцам — текстовый график.
    months = [point for point in data.monthly if point.income or point.expense]
    if months:
        max_value = max((max(point.expense, point.income) for point in months), default=0)
        if max_value > 0:
            lines.append("")
            lines.append("<b>Динамика по месяцам</b>")
            for point in months[-6:]:
                bar = progress_bar(float(point.expense / max_value * 100), width=10)
                lines.append(
                    f"{format_period_ru(point.period)[:12]}: "
                    f"<code>{bar}</code> {escape_html(format_amount(point.expense, currency))}"
                )

    keyboard = Keyboard().row(
        callback_button("Сегодня", "stats:show", "today"),
        callback_button("7 дней", "stats:show", "week"),
        callback_button("Месяц", "stats:show", "month"),
    )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.STATS_MENU
    return view

