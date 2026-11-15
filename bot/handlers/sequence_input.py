"""Обработка текстового ввода в многошаговых сценариях (FSM).

Здесь собраны экраны, где бот ждёт текстовое значение: даты периода истории,
новые значения полей операции, сумма бюджета, параметры цели, имя категории
и вопрос AI-помощнику.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from bot.context import Context
from bot.services.budgets import BudgetService
from bot.services.goals import GoalService
from bot.services.transactions import TransactionService
from bot.states import Screen
from bot.utils.dates import current_period, custom_range, parse_date_ru
from bot.utils.money import format_money, parse_amount
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import cancel_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


async def handle_sequence_input(ctx: Context, text: str) -> list[ScreenView]:
    """Маршрутизация ввода по текущему экрану."""
    value = (text or "").strip()
    handlers = {
        Screen.HISTORY_CUSTOM_FROM: _history_custom_from,
        Screen.HISTORY_CUSTOM_TO: _history_custom_to,
        Screen.HISTORY_EDIT_VALUE: _history_edit_value,
        Screen.BUDGET_AMOUNT: _budget_amount,
        Screen.GOAL_NAME: _goal_name,
        Screen.GOAL_TARGET: _goal_target,
        Screen.GOAL_DEADLINE: _goal_deadline,
        Screen.GOAL_CONTRIBUTE: _goal_contribute,
        Screen.SETTINGS_CATEGORY_ADD_NAME: _category_add_name,
        Screen.SETTINGS_CATEGORY_RENAME: _category_rename,
        Screen.AI_ASSISTANT: _ai_question,
    }
    handler = handlers.get(ctx.state.screen)
    if handler is None:
        return []
    result = await handler(ctx, value)
    return result if isinstance(result, list) else [result]


# --- история: произвольный период -----------------------------------------


async def _history_custom_from(ctx: Context, value: str) -> ScreenView:
    start = parse_date_ru(value, tz_name=ctx.user.timezone)
    if start is None:
        return ScreenView(
            text="⚠️ Не понял дату. Введите, например, 01.11.2026:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.HISTORY_CUSTOM_FROM)
    return ScreenView(
        text=f"Начало: <b>{start:%d.%m.%Y}</b>\n\nТеперь дата окончания:",
        keyboard=cancel_keyboard(),
    ).with_state(Screen.HISTORY_CUSTOM_TO, range_start=start.isoformat())


async def _history_custom_to(ctx: Context, value: str) -> list[ScreenView]:
    from bot.handlers.history import show_period

    try:
        start = date_cls.fromisoformat(str(ctx.state.get("range_start")))
    except (TypeError, ValueError):
        return [main_menu_screen("⚠️ Период не задан. Начните заново.")]

    end = parse_date_ru(value, tz_name=ctx.user.timezone)
    if end is None:
        return [
            ScreenView(
                text="⚠️ Не понял дату окончания. Введите, например, 06.11.2026:",
                keyboard=cancel_keyboard(),
            ).with_state(Screen.HISTORY_CUSTOM_TO, range_start=start.isoformat())
        ]
    return [await show_period(ctx, custom_range(start, end))]


async def _history_edit_value(ctx: Context, value: str) -> list[ScreenView]:
    from bot.handlers.history import history_item_for

    transaction_id = ctx.state.int("transaction_id")
    field = str(ctx.state.get("edit_field") or "")
    if transaction_id is None:
        return [main_menu_screen("⚠️ Операция не найдена.")]

    service = TransactionService(ctx.db)
    retry_state = {
        "screen": Screen.HISTORY_EDIT_VALUE,
        "transaction_id": transaction_id,
        "edit_field": field,
    }
    try:
        if field == "amount":
            parsed = parse_amount(value)
            if parsed is None:
                return [ScreenView(text="⚠️ Введите сумму, например 1250,50:",
                                   keyboard=cancel_keyboard()).with_state(**retry_state)]
            updated = await service.update(transaction_id, ctx.user.id, amount=parsed.amount)
        elif field == "comment":
            comment = "" if value in {"-", "—"} else value[:500]
            updated = await service.update(transaction_id, ctx.user.id, comment=comment)
        elif field == "date":
            parsed_date = parse_date_ru(value, tz_name=ctx.user.timezone)
            if parsed_date is None:
                return [ScreenView(text="⚠️ Введите дату, например 05.11.2026:",
                                   keyboard=cancel_keyboard()).with_state(**retry_state)]
            updated = await service.update(
                transaction_id, ctx.user.id, transaction_date=parsed_date
            )
        else:
            updated = await service.get(transaction_id, ctx.user.id)
    except Exception as exc:
        logger.info("Не удалось изменить операцию: %s", exc)
        return [ScreenView(text=f"⚠️ {escape_html(str(exc))}\n\nВведите значение ещё раз:",
                           keyboard=cancel_keyboard()).with_state(**retry_state)]

    if updated is None:
        return [main_menu_screen("⚠️ Операция не найдена.")]
    view = await history_item_for(ctx, updated.id)
    view.text = "✅ Операция обновлена.\n\n" + view.text
    return [view]


# --- бюджет ----------------------------------------------------------------


async def _budget_amount(ctx: Context, value: str) -> ScreenView:
    from bot.handlers.budgets import budget_menu_view

    parsed = parse_amount(value)
    if parsed is None:
        return ScreenView(
            text="⚠️ Не удалось распознать сумму. Например: 50000:",
            keyboard=cancel_keyboard(),
        ).with_state(
            Screen.BUDGET_AMOUNT,
            category_id=ctx.state.get("category_id"),
            category_name=ctx.state.get("category_name"),
        )

    try:
        await BudgetService(ctx.db).set_budget(
            ctx.user.id,
            current_period(ctx.user.timezone),
            parsed.amount,
            category_id=ctx.state.int("category_id"),
        )
    except ValueError as exc:
        return main_menu_screen(f"⚠️ {escape_html(str(exc))}")

    scope = ctx.state.get("category_name") or "общий"
    await ctx.states.reset(ctx.user.id)
    return await budget_menu_view(
        ctx,
        notice=(
            "✅ Лимит сохранён: "
            f"{escape_html(format_money(parsed.amount, currency=ctx.user.currency))} "
            f"({escape_html(str(scope))})."
        ),
    )


# --- цели ------------------------------------------------------------------


async def _goal_name(ctx: Context, value: str) -> ScreenView:
    if len(value) < 2:
        return ScreenView(
            text="⚠️ Название слишком короткое. Например, «Отпуск»:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.GOAL_NAME)
    return ScreenView(
        text=f"Цель: <b>{escape_html(value)}</b>\n\nТеперь укажите целевую сумму:",
        keyboard=cancel_keyboard(),
    ).with_state(Screen.GOAL_TARGET, name=value[:128])


async def _goal_target(ctx: Context, value: str) -> ScreenView:
    parsed = parse_amount(value)
    if parsed is None:
        return ScreenView(
            text="⚠️ Не удалось распознать сумму. Например: 100000:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.GOAL_TARGET, name=ctx.state.get("name"))

    keyboard = Keyboard().row(callback_button("➡️ Без срока", "goal:no_deadline"))
    keyboard.row(callback_button("✖️ Отмена", "menu:main"))
    amount_text = format_money(parsed.amount, currency=ctx.user.currency)
    return ScreenView(
        text=(
            f"Сумма цели: <b>{escape_html(amount_text)}</b>\n\n"
            "Укажите срок (ДД.ММ.ГГГГ) или пропустите шаг:"
        ),
        keyboard=keyboard,
    ).with_state(Screen.GOAL_DEADLINE, name=ctx.state.get("name"), target=str(parsed.amount))


async def _goal_deadline(ctx: Context, value: str) -> ScreenView:
    deadline = parse_date_ru(value, tz_name=ctx.user.timezone)
    if deadline is None:
        keyboard = Keyboard().row(callback_button("➡️ Без срока", "goal:no_deadline"))
        keyboard.row(callback_button("✖️ Отмена", "menu:main"))
        return ScreenView(
            text="⚠️ Не понял дату. Введите ДД.ММ.ГГГГ или выберите «Без срока»:",
            keyboard=keyboard,
        ).with_state(
            Screen.GOAL_DEADLINE, name=ctx.state.get("name"), target=ctx.state.get("target")
        )
    return await create_goal_view(ctx, deadline)


async def create_goal_view(ctx: Context, deadline: date_cls | None) -> ScreenView:
    """Создать цель из данных состояния и вернуть меню целей."""
    from bot.handlers.goals import goals_menu_view

    try:
        goal = await GoalService(ctx.db).create(
            ctx.user.id,
            str(ctx.state.get("name") or "Цель"),
            ctx.state.get("target") or 0,
            deadline=deadline,
        )
    except ValueError as exc:
        return main_menu_screen(f"⚠️ {escape_html(str(exc))}")

    await ctx.states.reset(ctx.user.id)
    amount_text = format_money(goal.target_amount, currency=ctx.user.currency)
    return await goals_menu_view(
        ctx, notice=f"✅ Цель «{escape_html(goal.name)}» создана: {escape_html(amount_text)}"
    )


async def _goal_contribute(ctx: Context, value: str) -> ScreenView:
    from bot.handlers.goals import goal_detail_view

    goal_id = ctx.state.int("goal_id")
    if goal_id is None:
        return main_menu_screen("⚠️ Цель не найдена.")
    parsed = parse_amount(value)
    if parsed is None:
        return ScreenView(
            text="⚠️ Не удалось распознать сумму. Например: 5000:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.GOAL_CONTRIBUTE, goal_id=goal_id)

    goal = await GoalService(ctx.db).contribute(goal_id, ctx.user.id, parsed.amount)
    if goal is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Цель не найдена.")
    amount_text = format_money(parsed.amount, currency=ctx.user.currency)
    return await goal_detail_view(ctx, goal, notice=f"✅ Отложено {escape_html(amount_text)}.")


# --- категории -------------------------------------------------------------


async def _category_add_name(ctx: Context, value: str) -> ScreenView | list[ScreenView]:
    from bot.handlers.categories import create_category_and_return

    type_ = str(ctx.state.get("category_type") or "expense")
    if len(value) < 2:
        return ScreenView(
            text="⚠️ Название слишком короткое. Введите название категории:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.SETTINGS_CATEGORY_ADD_NAME, category_type=type_)
    return [await create_category_and_return(ctx, value, type_)]


async def _category_rename(ctx: Context, value: str) -> ScreenView | list[ScreenView]:
    from bot.handlers.categories import categories_menu_view

    category_id = ctx.state.int("category_id")
    if category_id is None or len(value) < 2:
        return main_menu_screen("⚠️ Не удалось переименовать категорию.")
    await ctx.categories.rename(category_id, ctx.user.id, value)
    await ctx.states.reset(ctx.user.id)
    return [await categories_menu_view(ctx, notice="✅ Категория переименована.")]


# --- AI-помощник -----------------------------------------------------------


async def _ai_question(ctx: Context, value: str) -> list[ScreenView]:
    """Вопрос AI-помощнику: списываем лимит только при успешном ответе."""
    from bot.handlers.ai import ask_assistant
    from bot.services.ai_base import AIError, AINotConfiguredError
    from bot.utils.ui.keyboards import Keyboard, callback_button

    if len(value) < 3:
        return [
            ScreenView(
                text="⚠️ Слишком короткий вопрос. Напишите подробнее:",
                keyboard=cancel_keyboard(),
            ).with_state(Screen.AI_ASSISTANT)
        ]

    try:
        answer = await ask_assistant(ctx, value)
    except AINotConfiguredError:
        return [main_menu_screen(
            "AI-помощник пока не подключён (не задан ключ AI Dostup в настройках)."
        )]
    except AIError as exc:
        logger.warning("AI-помощник недоступен: %s", exc)
        return [main_menu_screen(
            "⚠️ AI-помощник временно недоступен. Запрос не списан с лимита.\n"
            "Попробуйте ещё раз чуть позже."
        )]

    # Успешный ответ модели — списываем один AI-запрос (ТЗ п. 5.3, 12).
    from bot.services.ai_limits import AILimitService

    await AILimitService(ctx.db, ctx.settings.ai_free_requests).consume(ctx.user.id)

    view = ScreenView(
        text=f"🤖 {answer}\n\n<i>Это подсказка, а не финансовое решение.</i>",
        keyboard=Keyboard().row(
            callback_button("💬 Ещё вопрос", "ai:ask"),
            callback_button("🏠 Главное меню", "menu:main"),
        ),
    )
    view.next_screen = Screen.AI_MENU
    view.state_data = {}
    return [view]


