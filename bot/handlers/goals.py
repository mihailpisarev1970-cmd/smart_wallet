"""Цели накопления (ТЗ п. 3.10).

Пользователь создаёт цель (название, сумма, срок), вносит суммы, видит
прогресс и сколько осталось. Напоминания — по запросу, без фоновых рассылок.
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.services.goals import GoalRecord, GoalService
from bot.states import Screen
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import cancel_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_date_ru, progress_bar

logger = logging.getLogger(__name__)


def goal_line(goal: GoalRecord, currency: str) -> str:
    """Одна строка списка целей."""
    bar = progress_bar(goal.percent, width=10)
    return (
        f"<b>{escape_html(goal.name)}</b>\n"
        f"<code>{bar}</code> "
        f"{escape_html(format_money(goal.saved_amount, currency=currency))} "
        f"из {escape_html(format_money(goal.target_amount, currency=currency))}"
    )


async def goals_menu_view(ctx: Context, *, notice: str = "") -> ScreenView:
    """Список целей."""
    goals = await GoalService(ctx.db).list(ctx.user.id)
    currency = ctx.user.currency

    lines = []
    if notice:
        lines.extend([notice, ""])
    lines.append("<b>🏦 Цели накопления</b>")
    lines.append("")

    if not goals:
        lines.append(
            "Целей пока нет. Создайте цель, например «Отпуск» или «Новый телефон», "
            "и отслеживайте прогресс."
        )
    else:
        for goal in goals:
            lines.append(goal_line(goal, currency))
            if goal.deadline:
                days_left = goal.days_left or 0
                deadline_text = format_date_ru(goal.deadline)
                if days_left >= 0:
                    lines.append(f"Срок: {deadline_text} (осталось дней: {days_left})")
                else:
                    lines.append(f"Срок истёк: {deadline_text}")
            lines.append("")

    keyboard = Keyboard().row(callback_button("➕ Новая цель", "goal:new"))
    for goal in goals[:8]:
        keyboard.rows.append(
            [callback_button(f"📌 {goal.name}"[:40], "goal:detail", str(goal.id))]
        )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.GOALS_MENU
    view.state_data = {}
    return view


@router.callback("goals:open")
@router.command("/goals")
async def goals_menu(ctx: Context) -> ScreenView:
    """Открыть цели накопления."""
    return await goals_menu_view(ctx)


@router.callback("goal:new")
async def goal_new(ctx: Context) -> ScreenView:
    """Создание цели: шаг 1 — название."""
    return ScreenView(
        text=(
            "<b>Новая цель</b>\n\n"
            "Шаг 1 из 3. Как назовём цель? Например: «Отпуск», «Ремонт»."
        ),
        keyboard=cancel_keyboard(),
    ).with_state(Screen.GOAL_NAME)


@router.callback("goal:no_deadline")
async def goal_no_deadline(ctx: Context) -> ScreenView:
    """Создать цель без срока."""
    from bot.handlers.sequence_input import create_goal_view

    return await create_goal_view(ctx, None)


@router.callback("goal:detail")
async def goal_detail(ctx: Context) -> ScreenView:
    """Карточка цели."""
    goal_id = ctx.arg_int()
    goal = await GoalService(ctx.db).get(goal_id, ctx.user.id) if goal_id else None
    if goal is None:
        return main_menu_screen("⚠️ Цель не найдена.")
    return await goal_detail_view(ctx, goal)


async def goal_detail_view(ctx: Context, goal: GoalRecord, *, notice: str = "") -> ScreenView:
    """Карточка цели с прогрессом."""
    currency = ctx.user.currency
    bar = progress_bar(goal.percent, width=14)
    lines = []
    if notice:
        lines.extend([notice, ""])
    lines.extend(
        [
            f"<b>🏦 {escape_html(goal.name)}</b>",
            "",
            f"<code>{bar}</code>",
            f"Накоплено: <b>{escape_html(format_money(goal.saved_amount, currency=currency))}</b>",
            f"Цель: {escape_html(format_money(goal.target_amount, currency=currency))}",
            f"Осталось: {escape_html(format_money(goal.remaining, currency=currency))}",
        ]
    )
    if goal.deadline:
        lines.append(f"Срок: {format_date_ru(goal.deadline)}")
        days_left = goal.days_left or 0
        if days_left > 0 and goal.remaining > 0:
            per_month = goal.remaining / (max(days_left, 1) / 30)
            lines.append(
                "Чтобы успеть, нужно откладывать ~"
                f"{escape_html(format_money(per_month, currency=currency))} в месяц."
            )
    if goal.is_completed:
        lines.append("")
        lines.append("🎉 Цель достигнута!")

    keyboard = Keyboard().row(callback_button("💰 Отложить", "goal:contribute", str(goal.id)))
    keyboard.row(callback_button("🗑 Удалить цель", "goal:delete", str(goal.id)))
    keyboard.row(callback_button("« Все цели", "goals:open"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.GOAL_DETAIL
    view.state_data = {"goal_id": goal.id}
    return view


@router.callback("goal:contribute")
async def goal_contribute(ctx: Context) -> ScreenView:
    """Запрос суммы для пополнения цели."""
    goal_id = ctx.arg_int() or ctx.state.int("goal_id")
    goal = await GoalService(ctx.db).get(goal_id, ctx.user.id) if goal_id else None
    if goal is None:
        return main_menu_screen("⚠️ Цель не найдена.")
    return ScreenView(
        text=f"<b>{escape_html(goal.name)}</b>\n\nКакую сумму отложить? Например: 5000",
        keyboard=cancel_keyboard(),
    ).with_state(Screen.GOAL_CONTRIBUTE, goal_id=goal.id)


@router.callback("goal:delete")
async def goal_delete(ctx: Context) -> ScreenView:
    """Подтверждение удаления цели."""
    goal_id = ctx.arg_int() or ctx.state.int("goal_id")
    goal = await GoalService(ctx.db).get(goal_id, ctx.user.id) if goal_id else None
    if goal is None:
        return main_menu_screen("⚠️ Цель не найдена.")
    keyboard = Keyboard().row(
        callback_button("🗑 Да, удалить", "goal:delete_confirm", str(goal.id)),
        callback_button("✖️ Нет", "goal:detail", str(goal.id)),
    )
    view = ScreenView(
        text=(
            f"<b>Удалить цель «{escape_html(goal.name)}»?</b>\n\n"
            "Данные о накоплениях будут удалены."
        ),
        keyboard=keyboard,
    )
    view.next_screen = Screen.GOAL_DELETE_CONFIRM
    return view


@router.callback("goal:delete_confirm")
async def goal_delete_confirm(ctx: Context) -> ScreenView:
    """Удалить цель после подтверждения."""
    goal_id = ctx.arg_int() or ctx.state.int("goal_id")
    if goal_id is None:
        return main_menu_screen("⚠️ Цель не найдена.")
    deleted = await GoalService(ctx.db).delete(goal_id, ctx.user.id)
    await ctx.states.reset(ctx.user.id)
    return await goals_menu_view(
        ctx, notice="🗑 Цель удалена." if deleted else "⚠️ Цель не найдена."
    )

