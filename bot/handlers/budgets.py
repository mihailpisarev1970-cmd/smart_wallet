"""Месячный бюджет и лимиты по категориям (ТЗ п. 3.9).

Показываем использованную сумму, остаток и прогресс. Пороговые уведомления
(50/80/100%) отправляются как ответ на действие пользователя — при записи
операции и по кнопке «Проверить бюджет».
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.services.budgets import BudgetService
from bot.states import Screen
from bot.utils.dates import current_period
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import cancel_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_period_ru, progress_bar

logger = logging.getLogger(__name__)


def _budget_line(title: str, spent, amount, currency: str) -> str:
    percent = float(spent / amount * 100) if amount else 0.0
    bar = progress_bar(percent)
    left = amount - spent
    return (
        f"<b>{escape_html(title)}</b>: {escape_html(format_money(spent, currency=currency))} "
        f"из {escape_html(format_money(amount, currency=currency))}\n"
        f"<code>{bar}</code> остаток "
        f"{escape_html(format_money(max(left, 0), currency=currency))}"
    )


async def budget_menu_view(ctx: Context, *, notice: str = "") -> ScreenView:
    """Экран бюджетов текущего месяца."""
    period = current_period(ctx.user.timezone)
    service = BudgetService(ctx.db)
    status = await service.status(ctx.user.id, period)
    currency = ctx.user.currency

    lines = []
    if notice:
        lines.extend([notice, ""])
    lines.append(f"<b>🎯 Бюджет на {format_period_ru(period)}</b>")
    lines.append("")

    if not status.has_budgets:
        lines.append(
            "Лимиты пока не заданы.\n"
            "Поставьте общий лимит на месяц или лимиты по категориям — "
            "я предупрежу при 50%, 80% и 100% расхода."
        )
    else:
        if status.overall:
            lines.append(
                _budget_line("Общий бюджет", status.overall.spent, status.overall.amount, currency)
            )
            lines.append("")
        if status.categories:
            lines.append("<b>Лимиты по категориям</b>")
            for record in status.categories:
                lines.append(_budget_line(record.title, record.spent, record.amount, currency))
                lines.append("")
        lines.append(
            f"Всего потрачено за месяц: "
            f"<b>{escape_html(format_money(status.total_spent, currency=currency))}</b>"
        )

    keyboard = Keyboard().row(
        callback_button("💰 Общий лимит", "budget:set", "overall"),
        callback_button("🏷 Лимит по категории", "budget:set", "category"),
    )
    keyboard.row(callback_button("🔄 Проверить бюджет", "budget:check"))
    if status.has_budgets:
        keyboard.row(callback_button("🗑 Удалить лимит", "budget:remove_list"))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.BUDGET_MENU
    view.state_data = {}
    return view


@router.callback("budget:open")
@router.command("/budget")
async def budget_menu(ctx: Context) -> ScreenView:
    return await budget_menu_view(ctx)


@router.callback("budget:set")
async def budget_set(ctx: Context) -> ScreenView:
    """Начало установки лимита: общий или по категории."""
    scope = ctx.arg or "overall"
    if scope == "category":
        categories = await ctx.categories.list_for_user(ctx.user.id, "expense")
        keyboard = Keyboard()
        from bot.constants import CATEGORY_EMOJI

        buttons = [
            callback_button(
                f"{CATEGORY_EMOJI.get(item.name, '•')} {item.name}",
                "budget:category",
                str(item.id),
            )
            for item in categories
        ]
        keyboard.add(*buttons, per_row=2)
        keyboard.row(callback_button("« Назад", "budget:open"))
        view = ScreenView(
            text="<b>Лимит по какой категории?</b>", keyboard=keyboard
        )
        view.next_screen = Screen.BUDGET_CATEGORY
        return view

    return ScreenView(
        text=(
            "<b>Общий лимит на месяц</b>\n\n"
            "Введите сумму, которую готовы потратить за текущий месяц "
            f"({format_period_ru(current_period(ctx.user.timezone))}):"
        ),
        keyboard=cancel_keyboard(),
    ).with_state(Screen.BUDGET_AMOUNT, category_id=None, category_name=None)


@router.callback("budget:category")
async def budget_category_chosen(ctx: Context) -> ScreenView:
    """Категория выбрана — просим сумму лимита."""
    category_id = ctx.arg_int()
    category = await ctx.categories.get(category_id, ctx.user.id) if category_id else None
    if category is None:
        return main_menu_screen("⚠️ Категория не найдена.")
    return ScreenView(
        text=(
            f"<b>Лимит на «{escape_html(category.name)}»</b>\n\n"
            "Введите сумму месячного лимита по этой категории:"
        ),
        keyboard=cancel_keyboard(),
    ).with_state(
        Screen.BUDGET_AMOUNT, category_id=category.id, category_name=category.name
    )


@router.callback("budget:check")
async def budget_check(ctx: Context) -> ScreenView:
    """Проверка бюджета по запросу пользователя (ТЗ п. 3.9)."""
    from bot.services.budget_alerts import append_budget_alerts

    period = current_period(ctx.user.timezone)
    service = BudgetService(ctx.db)
    alerts = await service.check_thresholds(ctx.user.id, period)
    text = ""
    if alerts:
        # Переиспользуем логику уведомлений: показываем как «ответ на действие».
        class _FakeExpense:
            type = "expense"
            category_id = None

        text = await append_budget_alerts(ctx, _FakeExpense())
        await service.mark_alerts_sent(alerts)
    view = await budget_menu_view(ctx)
    if text:
        view.text = view.text + "\n" + text
    return view


@router.callback("budget:remove_list")
async def budget_remove_list(ctx: Context) -> ScreenView:
    """Список бюджетов для удаления."""
    period = current_period(ctx.user.timezone)
    budgets = await BudgetService(ctx.db).list_for_period(ctx.user.id, period)
    keyboard = Keyboard()
    for record in budgets:
        keyboard.rows.append(
            [callback_button(f"🗑 {record.title}"[:40], "budget:remove", str(record.id))]
        )
    keyboard.row(callback_button("« Назад", "budget:open"))
    view = ScreenView(
        text="<b>Какой лимит удалить?</b>", keyboard=keyboard
    )
    view.next_screen = Screen.BUDGET_MENU
    return view


@router.callback("budget:remove")
async def budget_remove(ctx: Context) -> ScreenView:
    """Удалить лимит."""
    budget_id = ctx.arg_int()
    if budget_id is None:
        return main_menu_screen("⚠️ Лимит не найден.")
    deleted = await BudgetService(ctx.db).delete(budget_id, ctx.user.id)
    notice = "🗑 Лимит удалён." if deleted else "⚠️ Лимит не найден."
    return await budget_menu_view(ctx, notice=notice)

