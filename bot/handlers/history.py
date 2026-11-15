"""История операций: просмотр, редактирование, удаление (ТЗ п. 3.7).

Периоды: сегодня, вчера, 7 дней, месяц, произвольный диапазон.
Редактирование и удаление — только своих операций и с подтверждением удаления.
"""

from __future__ import annotations

import logging
from datetime import date

from bot.constants import CATEGORY_EMOJI, EXPENSE
from bot.context import Context
from bot.router import router
from bot.services.statistics import StatisticsService
from bot.services.transactions import TransactionService
from bot.states import Screen
from bot.utils.dates import HISTORY_PERIODS, DateRange, custom_range, range_by_key
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import back_to_menu_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_date_ru

logger = logging.getLogger(__name__)

PAGE_SIZE = 8


def period_keyboard() -> Keyboard:
    keyboard = Keyboard()
    buttons = [callback_button(label, "history:period", key) for key, label in HISTORY_PERIODS]
    keyboard.add(*buttons, per_row=2)
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    return keyboard


def tx_line(record, currency: str) -> str:
    """Одна строка истории."""
    emoji = CATEGORY_EMOJI.get(record.category_name, "•")
    amount = format_money(record.amount, currency=record.currency or currency)
    comment = f" — {escape_html(record.comment)}" if record.comment else ""
    date_label = format_date_ru(record.transaction_date, with_year=False)
    return (
        f"<b>#{record.id}</b> {emoji} {escape_html(record.category_name)}: "
        f"{record.sign_symbol} {escape_html(amount)} ({date_label}){comment}"
    )


def range_from_state(ctx: Context) -> DateRange:
    """Восстановить текущий период истории из состояния."""
    data = ctx.state.data
    try:
        start = date.fromisoformat(str(data["range_start"]))
        end = date.fromisoformat(str(data["range_end"]))
        label = str(data.get("label") or "")
        date_range = custom_range(start, end)
        return DateRange(date_range.start, date_range.end, label or date_range.label)
    except (KeyError, ValueError):
        return range_by_key("month", ctx.user.timezone)


@router.callback("history:open")
@router.command("/history")
async def history_open(ctx: Context) -> ScreenView:
    """Выбор периода истории."""
    view = ScreenView(
        text="<b>🕘 История операций</b>\n\nЗа какой период показать операции?",
        keyboard=period_keyboard(),
    )
    return view.with_state(Screen.HISTORY_PERIOD)


@router.callback("history:period")
async def history_period(ctx: Context) -> ScreenView | list[ScreenView]:
    """Показать операции за выбранный период."""
    key = ctx.arg or "month"
    if key == "custom":
        view = ScreenView(
            text=(
                "<b>Свой период</b>\n\n"
                "Напишите дату начала в формате ДД.ММ.ГГГГ (например, 01.11.2026)."
            ),
            keyboard=back_to_menu_keyboard("✖️ Отмена"),
        )
        return view.with_state(Screen.HISTORY_CUSTOM_FROM)

    return await show_period(ctx, range_by_key(key, ctx.user.timezone), page=0)


async def show_period(ctx: Context, date_range: DateRange, *, page: int = 0) -> ScreenView:
    """Список операций за период с пагинацией."""
    service = TransactionService(ctx.db)
    total = await service.count_period(ctx.user.id, date_range)
    records = await service.list_period(
        ctx.user.id, date_range, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )

    state = {
        "range_start": date_range.start.isoformat(),
        "range_end": date_range.end.isoformat(),
        "label": date_range.label,
    }

    if total == 0:
        keyboard = Keyboard().row(
            callback_button("💸 Добавить расход", "tx:new", "expense"),
            callback_button("💰 Добавить доход", "tx:new", "income"),
        )
        keyboard.row(callback_button("🕘 Другой период", "history:open"))
        keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
        view = ScreenView(
            text=(
                f"<b>История: {date_range.label}</b>\n\n"
                "Операций нет. Добавьте расход или доход — они появятся здесь."
            ),
            keyboard=keyboard,
        )
        view.next_screen = Screen.HISTORY_LIST
        view.state_data = state
        return view

    stats = StatisticsService(ctx.db)
    totals = await stats.totals(ctx.user.id, date_range)

    lines = [
        f"<b>История: {date_range.label}</b>",
        f"Операций: {total} · расходы "
        f"{format_money(totals.expense, currency=ctx.user.currency)} · доходы "
        f"{format_money(totals.income, currency=ctx.user.currency)}",
        "",
    ]
    lines.extend(tx_line(record, ctx.user.currency) for record in records)

    pages = (total + PAGE_SIZE - 1) // PAGE_SIZE
    if pages > 1:
        lines.append("")
        lines.append(f"Страница {page + 1} из {pages}")

    keyboard = Keyboard()
    for record in records:
        emoji = "💸" if record.type == EXPENSE else "💰"
        keyboard.rows.append(
            [
                callback_button(
                    f"{emoji} #{record.id} {record.category_name[:16]}",
                    "history:item",
                    str(record.id),
                )
            ]
        )

    nav = []
    if page > 0:
        nav.append(callback_button("« Назад", "history:page", str(page - 1)))
    if page + 1 < pages:
        nav.append(callback_button("Далее »", "history:page", str(page + 1)))
    if nav:
        keyboard.rows.append(nav)
    keyboard.row(callback_button("🕘 Другой период", "history:open"))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.HISTORY_LIST
    view.state_data = {**state, "page": page}
    return view


@router.callback("history:page")
async def history_page(ctx: Context) -> ScreenView:
    """Переход между страницами истории."""
    return await show_period(ctx, range_from_state(ctx), page=ctx.arg_int() or 0)


@router.callback("history:item")
async def history_item(ctx: Context) -> ScreenView:
    """Карточка операции: редактировать или удалить."""
    transaction_id = ctx.arg_int()
    service = TransactionService(ctx.db)
    record = await service.get(transaction_id, ctx.user.id) if transaction_id else None
    if record is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Операция не найдена — возможно, уже удалена.")

    emoji = CATEGORY_EMOJI.get(record.category_name, "•")
    text = (
        f"<b>Операция #{record.id}</b>\n\n"
        f"Тип: {record.type_label}\n"
        f"Сумма: <b>{escape_html(format_money(record.amount, currency=record.currency))}</b>\n"
        f"Категория: {emoji} {escape_html(record.category_name)}\n"
        f"Дата: {format_date_ru(record.transaction_date)}\n"
        f"Источник: {record.source}"
    )
    if record.comment:
        text += f"\nКомментарий: {escape_html(record.comment)}"

    keyboard = Keyboard().row(
        callback_button("✏️ Изменить", "history:edit", str(record.id)),
        callback_button("🗑 Удалить", "history:delete", str(record.id)),
    )
    keyboard.row(callback_button("« К истории", "history:page", str(ctx.state.int("page") or 0)))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.HISTORY_ITEM
    view.state_data = {**ctx.state.data, "transaction_id": record.id}
    return view


@router.callback("history:edit")
async def history_edit(ctx: Context) -> ScreenView:
    """Меню редактирования операции."""
    transaction_id = ctx.arg_int() or ctx.state.int("transaction_id")
    record = (
        await TransactionService(ctx.db).get(transaction_id, ctx.user.id)
        if transaction_id
        else None
    )
    if record is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Операция не найдена.")

    keyboard = Keyboard().row(
        callback_button("💵 Сумму", "history:edit_field", "amount", str(record.id)),
        callback_button("🏷 Категорию", "history:edit_field", "category", str(record.id)),
    )
    keyboard.row(
        callback_button("📝 Комментарий", "history:edit_field", "comment", str(record.id)),
        callback_button("📅 Дату", "history:edit_field", "date", str(record.id)),
    )
    keyboard.row(callback_button("« К операции", "history:item", str(record.id)))

    view = ScreenView(text="<b>Что изменить?</b>", keyboard=keyboard)
    view.next_screen = Screen.HISTORY_ITEM
    view.state_data = {**ctx.state.data, "transaction_id": record.id}
    return view


@router.callback("history:edit_field")
async def history_edit_field(ctx: Context) -> ScreenView:
    """Запрос нового значения поля."""
    field = ctx.args[0] if ctx.args else "amount"
    transaction_id = ctx.arg_int(1) or ctx.state.int("transaction_id")
    record = (
        await TransactionService(ctx.db).get(transaction_id, ctx.user.id)
        if transaction_id
        else None
    )
    if record is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Операция не найдена.")

    if field == "category":
        categories = await ctx.categories.list_for_user(ctx.user.id, record.type)
        keyboard = Keyboard()
        buttons = [
            callback_button(
                f"{CATEGORY_EMOJI.get(category.name, '•')} {category.name}",
                "history:set_category",
                str(record.id),
                str(category.id),
            )
            for category in categories
        ]
        keyboard.add(*buttons, per_row=2)
        keyboard.row(callback_button("« Назад", "history:edit", str(record.id)))
        view = ScreenView(text="<b>Выберите новую категорию:</b>", keyboard=keyboard)
        view.next_screen = Screen.HISTORY_ITEM
        view.state_data = {**ctx.state.data, "transaction_id": record.id}
        return view

    prompts = {
        "amount": "Введите новую сумму (например, 1250,50):",
        "comment": "Введите новый комментарий (или «-», чтобы очистить):",
        "date": "Введите дату в формате ДД.ММ.ГГГГ (например, 05.11.2026):",
    }
    back_keyboard = Keyboard().row(
        callback_button("✖️ Отмена", "history:item", str(record.id))
    )
    view = ScreenView(
        text=prompts.get(field, "Введите новое значение:"), keyboard=back_keyboard
    )
    return view.with_state(
        Screen.HISTORY_EDIT_VALUE, transaction_id=record.id, edit_field=field
    )


@router.callback("history:set_category")
async def history_set_category(ctx: Context) -> ScreenView:
    """Применить новую категорию."""
    transaction_id = ctx.arg_int(0)
    category_id = ctx.arg_int(1)
    if transaction_id is None or category_id is None:
        return main_menu_screen("⚠️ Некорректный выбор категории.")
    updated = await TransactionService(ctx.db).update(
        transaction_id, ctx.user.id, category_id=category_id
    )
    if updated is None:
        return main_menu_screen("⚠️ Операция не найдена.")
    return await history_item_for(ctx, updated.id)


async def history_item_for(ctx: Context, transaction_id: int) -> ScreenView:
    """Показать карточку операции по её id."""
    saved_args = ctx.args
    ctx.args = [str(transaction_id)]
    try:
        return await history_item(ctx)
    finally:
        ctx.args = saved_args


@router.callback("history:delete")
async def history_delete(ctx: Context) -> ScreenView:
    """Подтверждение удаления (ТЗ п. 3.7)."""
    transaction_id = ctx.arg_int()
    record = (
        await TransactionService(ctx.db).get(transaction_id, ctx.user.id)
        if transaction_id
        else None
    )
    if record is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Операция не найдена.")

    amount = format_money(record.amount, currency=record.currency)
    keyboard = Keyboard().row(
        callback_button("🗑 Да, удалить", "history:delete_confirm", str(record.id)),
    )
    keyboard.row(callback_button("✖️ Нет, оставить", "history:item", str(record.id)))
    text = (
        "<b>Удалить операцию?</b>\n\n"
        f"#{record.id} {escape_html(record.category_name)}: "
        f"{record.sign_symbol} {escape_html(amount)}\n"
        f"Дата: {format_date_ru(record.transaction_date)}\n\n"
        "Это действие нельзя отменить."
    )
    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.HISTORY_DELETE_CONFIRM
    view.state_data = {**ctx.state.data, "transaction_id": record.id}
    return view


@router.callback("history:delete_confirm")
async def history_delete_confirm(ctx: Context) -> ScreenView:
    """Удалить операцию после подтверждения."""
    transaction_id = ctx.arg_int() or ctx.state.int("transaction_id")
    if transaction_id is None:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Операция не найдена.")

    deleted = await TransactionService(ctx.db).delete(transaction_id, ctx.user.id)
    await ctx.states.reset(ctx.user.id)
    if not deleted:
        return main_menu_screen("⚠️ Операция уже удалена.")
    logger.info("Пользователь %s удалил операцию #%s", ctx.user.id, transaction_id)
    return main_menu_screen(f"🗑 Операция #{transaction_id} удалена.")



