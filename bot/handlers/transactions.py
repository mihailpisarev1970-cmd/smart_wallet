"""Добавление расхода и дохода кнопками (ТЗ п. 3.3, 3.4).

Шаги: тип → сумма → категория → комментарий (можно пропустить) → подтверждение.
Сумма и категория проверяются; запись выполняется только после подтверждения.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls

from bot.constants import CATEGORY_EMOJI, EXPENSE, INCOME, SOURCE_BUTTON
from bot.context import Context
from bot.router import router
from bot.services.transactions import TransactionError, TransactionService
from bot.states import Screen
from bot.utils.dates import today_in_tz
from bot.utils.money import format_money, parse_amount
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import cancel_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_date_ru

logger = logging.getLogger(__name__)

TYPE_TITLES = {EXPENSE: "расход", INCOME: "доход"}


def _category_buttons(categories: list) -> Keyboard:
    """Клавиатура категорий: по 2 в ряд, с эмодзи."""
    keyboard = Keyboard()
    buttons = [
        callback_button(
            f"{CATEGORY_EMOJI.get(category.name, '•')} {category.name}",
            "tx:cat",
            str(category.id),
        )
        for category in categories
    ]
    keyboard.add(*buttons, per_row=2)
    keyboard.row(callback_button("✏️ Другая категория", "tx:new_category"))
    keyboard.row(callback_button("✖️ Отмена", "menu:main"))
    return keyboard


async def ask_amount_view(ctx: Context, type_: str, error: str | None = None) -> ScreenView:
    """Экран ввода суммы."""
    title = TYPE_TITLES[type_]
    text = (
        f"<b>Новый {title}</b>\n\n"
        "Введите сумму: можно «1250», «1 250,50» или «1,5к»."
    )
    if error:
        text = f"⚠️ {error}\n\n{text}"
    return ScreenView(text=text, keyboard=cancel_keyboard()).with_state(
        Screen.TX_AMOUNT, type=type_
    )


@router.callback("tx:new")
async def tx_new(ctx: Context) -> ScreenView | list[ScreenView]:
    """Начало добавления операции: ``tx:new:expense`` / ``tx:new:income``."""
    if not ctx.user.onboarding_completed:
        from bot.handlers.start import start_handler

        return await start_handler(ctx)
    type_ = ctx.arg if ctx.arg in {EXPENSE, INCOME} else EXPENSE
    return await ask_amount_view(ctx, type_)


@router.callback("tx:type")
async def tx_change_type(ctx: Context) -> ScreenView:
    """Смена типа операции на шаге суммы."""
    type_ = ctx.arg if ctx.arg in {EXPENSE, INCOME} else EXPENSE
    return await ask_amount_view(ctx, type_)


async def handle_amount_input(ctx: Context, text: str) -> ScreenView:
    """Обработать ввод суммы (общий код для текстового ввода)."""
    state_type = ctx.state.get("type", EXPENSE)
    parsed = parse_amount(text)
    if parsed is None:
        return await ask_amount_view(
            ctx, state_type, "Не удалось распознать сумму. Например: 1250 или 1 250,50"
        )

    categories = await ctx.categories.list_for_user(ctx.user.id, state_type)
    title = TYPE_TITLES[state_type]
    amount_text = format_money(parsed.amount, currency=ctx.user.currency)
    view = ScreenView(
        text=f"Сумма {title}а: <b>{escape_html(amount_text)}</b>\n\nВыберите категорию:",
        keyboard=_category_buttons(categories),
    ).with_state(
        Screen.TX_CATEGORY,
        type=state_type,
        amount=str(parsed.amount),
        date=today_in_tz(ctx.user.timezone).isoformat(),
    )
    # Сохраняем сразу: следующие шаги (категория → подтверждение) читают данные
    # из состояния, в том числе после перезапуска бота.
    await ctx.states.set(ctx.user.id, Screen.TX_CATEGORY, view.state_data or {})
    return view


@router.callback("tx:cat")
async def tx_choose_category(ctx: Context) -> ScreenView | list[ScreenView]:
    """Выбор категории из списка."""
    state_type = ctx.state.get("type", EXPENSE)
    category_id = ctx.arg_int()
    if category_id is None:
        return await ask_amount_view(ctx, state_type, "Категория не выбрана.")

    category = await ctx.categories.get(category_id, ctx.user.id)
    if category is None or category.type != state_type:
        return await ask_amount_view(ctx, state_type, "Категория не найдена.")

    amount_text = format_money(ctx.state.get("amount") or "0", currency=ctx.user.currency)
    text = (
        f"<b>{TYPE_TITLES[state_type].capitalize()}: {escape_html(amount_text)}</b>\n"
        f"Категория: {escape_html(category.name)}\n\n"
        "Добавьте комментарий (например, «обед с коллегами») или пропустите шаг."
    )
    view = ScreenView(text=text)
    view.keyboard.row(callback_button("➡️ Пропустить", "tx:comment_skip"))
    view.keyboard.row(callback_button("✖️ Отмена", "menu:main"))
    view.with_state(
        Screen.TX_COMMENT,
        type=state_type,
        amount=ctx.state.get("amount"),
        category_id=category.id,
        category_name=category.name,
    )
    # Фиксируем выбор: экран подтверждения читает данные из состояния.
    await ctx.states.set(ctx.user.id, Screen.TX_COMMENT, view.state_data or {})
    return view


@router.callback("tx:new_category")
async def tx_new_category(ctx: Context) -> ScreenView:
    """Создать категорию на лету: пользователь пишет название текстом."""
    state_type = ctx.state.get("type", EXPENSE)
    return ScreenView(
        text=f"Напишите название новой категории {TYPE_TITLES[state_type]}а (до 64 символов):",
        keyboard=cancel_keyboard(),
    ).with_state(
        Screen.TX_CATEGORY,
        type=state_type,
        amount=ctx.state.get("amount"),
        creating_category=True,
    )


@router.callback("tx:comment_skip")
async def tx_comment_skip(ctx: Context) -> ScreenView:
    """Перейти к подтверждению без комментария."""
    return await build_confirm_view(ctx, comment="")


async def build_confirm_view(ctx: Context, comment: str) -> ScreenView:
    """Экран подтверждения перед сохранением."""
    state_type = ctx.state.get("type", EXPENSE)
    amount = ctx.state.get("amount") or "0"
    category_name = ctx.state.get("category_name") or "—"
    op_date = str(ctx.state.get("date") or today_in_tz(ctx.user.timezone).isoformat())
    if ctx.state.get("comment") is not None and not comment:
        comment = str(ctx.state.get("comment") or "")
    amount_text = format_money(amount, currency=ctx.user.currency)
    title = TYPE_TITLES[state_type]

    try:
        date_label = format_date_ru(date_cls.fromisoformat(op_date))
    except ValueError:
        date_label = op_date

    lines = [
        f"<b>Проверьте {title}:</b>",
        f"Сумма: <b>{escape_html(amount_text)}</b>",
        f"Категория: {escape_html(str(category_name))}",
        f"Дата: {date_label}",
    ]
    if comment:
        lines.append(f"Комментарий: {escape_html(comment)}")

    keyboard = Keyboard().row(callback_button("✅ Сохранить", "tx:save"))
    keyboard.row(callback_button("✖️ Отмена", "menu:main"))
    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.with_state(
        Screen.TX_CONFIRM,
        type=state_type,
        amount=str(amount),
        category_id=ctx.state.get("category_id"),
        category_name=category_name,
        date=op_date,
        comment=comment,
    )
    await ctx.states.set(ctx.user.id, Screen.TX_CONFIRM, view.state_data or {})
    return view


@router.callback("tx:save")
async def tx_save(ctx: Context) -> ScreenView:
    """Сохранить операцию в БД (только после подтверждения)."""
    service = TransactionService(ctx.db)
    state_type = ctx.state.get("type", EXPENSE)
    category_name = ctx.state.get("category_name")

    try:
        record = await service.create(
            user_id=ctx.user.id,
            type_=state_type,
            amount=ctx.state.get("amount") or 0,
            currency=ctx.user.currency,
            category_id=ctx.state.int("category_id"),
            comment=ctx.state.get("comment") or "",
            source=SOURCE_BUTTON,
            tz_name=ctx.user.timezone,
        )
    except TransactionError as exc:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen(f"⚠️ {escape_html(str(exc))}\n\nВозвращаемся в меню.")

    await ctx.states.reset(ctx.user.id)
    emoji = CATEGORY_EMOJI.get(category_name or record.category_name, "•")
    text = (
        f"✅ <b>{record.type_label} записан</b>\n\n"
        f"Сумма: <b>{escape_html(format_money(record.amount, currency=record.currency))}</b>\n"
        f"Категория: {emoji} {escape_html(record.category_name)}\n"
        f"Дата: {format_date_ru(record.transaction_date)}"
    )
    if record.comment:
        text += f"\nКомментарий: {escape_html(record.comment)}"

    # ТЗ п. 3.9: уведомления о бюджете — как ответ на действие пользователя.
    from bot.services.budget_alerts import append_budget_alerts

    text += await append_budget_alerts(ctx, record)

    return main_menu_screen(text)

