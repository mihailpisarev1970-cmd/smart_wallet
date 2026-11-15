"""Управление категориями (ТЗ п. 3.5).

Пользователь может добавлять, переименовывать и удалять свои категории.
Удаление категории не удаляет операции — они переносятся в «Другое»
(или «Другие доходы»), логика — в ``CategoryRepository.delete_and_reassign``.
"""

from __future__ import annotations

import logging

from bot.constants import CATEGORY_EMOJI, EXPENSE, INCOME
from bot.context import Context
from bot.router import router
from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import cancel_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


async def categories_menu_view(ctx: Context, *, notice: str = "") -> ScreenView:
    """Экран управления категориями."""
    expense = await ctx.categories.list_for_user(ctx.user.id, EXPENSE)
    income = await ctx.categories.list_for_user(ctx.user.id, INCOME)

    lines = []
    if notice:
        lines.extend([notice, ""])
    lines.append("<b>🏷 Категории</b>")
    lines.append("")
    lines.append(f"<b>Расходы ({len(expense)})</b>")
    lines.append(", ".join(escape_html(item.name) for item in expense) or "—")
    lines.append("")
    lines.append(f"<b>Доходы ({len(income)})</b>")
    lines.append(", ".join(escape_html(item.name) for item in income) or "—")
    lines.append("")
    lines.append("<i>Удаление категории не удаляет операции: они переходят в «Другое».</i>")

    keyboard = Keyboard().row(
        callback_button("➕ Добавить расходную", "cat:add", EXPENSE),
        callback_button("➕ Добавить доходную", "cat:add", INCOME),
    )
    keyboard.row(
        callback_button("✏️ Расходные", "cat:manage", EXPENSE),
        callback_button("✏️ Доходные", "cat:manage", INCOME),
    )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.SETTINGS_CATEGORIES
    view.state_data = {}
    return view


@router.callback("cat:open")
async def categories_menu(ctx: Context) -> ScreenView:
    """Открыть управление категориями."""
    return await categories_menu_view(ctx)


@router.callback("cat:add")
async def category_add(ctx: Context) -> ScreenView:
    """Запрос названия новой категории."""
    type_ = ctx.arg if ctx.arg in {EXPENSE, INCOME} else EXPENSE
    label = "расходную" if type_ == EXPENSE else "доходную"
    return ScreenView(
        text=f"Введите название новой {label} категории (до 64 символов):",
        keyboard=cancel_keyboard(),
    ).with_state(Screen.SETTINGS_CATEGORY_ADD_NAME, category_type=type_)


async def create_category_and_return(ctx: Context, name: str, type_: str) -> ScreenView:
    """Создать категорию и вернуться к списку (или к выбору категории операции)."""
    created = await ctx.categories.create(ctx.user.id, name, type_)
    if created is None:
        return ScreenView(
            text=f"⚠️ Категория «{escape_html(name)}» уже существует. Введите другое название:",
            keyboard=cancel_keyboard(),
        ).with_state(Screen.SETTINGS_CATEGORY_ADD_NAME, category_type=type_)

    # Категория создавалась внутри сценария добавления операции:
    # возвращаем пользователя к выбору категории.
    if ctx.state.get("amount") is not None:
        from bot.handlers.transactions import _category_buttons

        categories = await ctx.categories.list_for_user(ctx.user.id, type_)
        return ScreenView(
            text=f"✅ Категория «{escape_html(created.name)}» добавлена.\n\nВыберите категорию:",
            keyboard=_category_buttons(categories),
        ).with_state(
            Screen.TX_CATEGORY,
            type=type_,
            amount=ctx.state.get("amount"),
            date=ctx.state.get("date"),
        )

    await ctx.states.reset(ctx.user.id)
    return await categories_menu_view(
        ctx, notice=f"✅ Категория «{escape_html(created.name)}» добавлена."
    )


@router.callback("cat:manage")
async def category_manage(ctx: Context) -> ScreenView:
    """Список категорий для переименования/удаления."""
    type_ = ctx.arg if ctx.arg in {EXPENSE, INCOME} else EXPENSE
    categories = await ctx.categories.list_for_user(ctx.user.id, type_)
    keyboard = Keyboard()
    for category in categories:
        emoji = CATEGORY_EMOJI.get(category.name, "•")
        keyboard.rows.append(
            [callback_button(f"{emoji} {category.name}"[:40], "cat:item", str(category.id))]
        )
    keyboard.row(callback_button("« Назад", "cat:open"))
    label = "расходную" if type_ == EXPENSE else "доходную"
    view = ScreenView(
        text=f"<b>Выберите {label} категорию</b> для изменения:", keyboard=keyboard
    )
    view.next_screen = Screen.SETTINGS_CATEGORY_MANAGE
    view.state_data = {"category_type": type_}
    return view


@router.callback("cat:item")
async def category_item(ctx: Context) -> ScreenView:
    """Действия с категорией: переименовать / удалить."""
    category_id = ctx.arg_int()
    category = await ctx.categories.get(category_id, ctx.user.id) if category_id else None
    if category is None:
        return main_menu_screen("⚠️ Категория не найдена.")

    keyboard = Keyboard().row(
        callback_button("✏️ Переименовать", "cat:rename", str(category.id)),
        callback_button("🗑 Удалить", "cat:delete", str(category.id)),
    )
    keyboard.row(callback_button("« Назад", "cat:manage", category.type))
    text = (
        f"<b>{CATEGORY_EMOJI.get(category.name, '•')} {escape_html(category.name)}</b>\n\n"
        f"Тип: {'расход' if category.type == EXPENSE else 'доход'}"
    )
    if category.is_default:
        text += "\n<i>Стандартная категория бота.</i>"
    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.SETTINGS_CATEGORY_MANAGE
    return view


@router.callback("cat:rename")
async def category_rename(ctx: Context) -> ScreenView:
    """Запрос нового названия категории."""
    category_id = ctx.arg_int()
    category = await ctx.categories.get(category_id, ctx.user.id) if category_id else None
    if category is None:
        return main_menu_screen("⚠️ Категория не найдена.")
    return ScreenView(
        text=f"Введите новое название для «{escape_html(category.name)}»:",
        keyboard=cancel_keyboard(),
    ).with_state(Screen.SETTINGS_CATEGORY_RENAME, category_id=category.id)


@router.callback("cat:delete")
async def category_delete(ctx: Context) -> ScreenView:
    """Подтверждение удаления категории."""
    category_id = ctx.arg_int()
    category = await ctx.categories.get(category_id, ctx.user.id) if category_id else None
    if category is None:
        return main_menu_screen("⚠️ Категория не найдена.")

    keyboard = Keyboard().row(
        callback_button("🗑 Да, удалить", "cat:delete_confirm", str(category.id))
    )
    keyboard.row(callback_button("✖️ Нет", "cat:item", str(category.id)))
    view = ScreenView(
        text=(
            f"<b>Удалить категорию «{escape_html(category.name)}»?</b>\n\n"
            "Операции этой категории сохранятся — они перейдут в «Другое». "
            "Лимит бюджета по категории будет удалён."
        ),
        keyboard=keyboard,
    )
    view.next_screen = Screen.SETTINGS_CATEGORY_DELETE
    return view


@router.callback("cat:delete_confirm")
async def category_delete_confirm(ctx: Context) -> ScreenView:
    """Удалить категорию, перенеся операции (ТЗ п. 3.5)."""
    category_id = ctx.arg_int()
    if category_id is None:
        return main_menu_screen("⚠️ Категория не найдена.")
    deleted, moved = await ctx.categories.delete_and_reassign(category_id, ctx.user.id)
    await ctx.states.reset(ctx.user.id)
    if not deleted:
        return main_menu_screen(
            "⚠️ Эту категорию удалить нельзя: она используется как резервная для операций."
        )
    notice = "✅ Категория удалена."
    if moved:
        notice += f" Перенесено операций: {moved}."
    return await categories_menu_view(ctx, notice=notice)


async def handle_new_category_input(ctx: Context, name: str) -> ScreenView:
    """Ввод названия категории во время добавления операции (``tx:new_category``)."""
    type_ = str(ctx.state.get("type") or EXPENSE)
    cleaned = (name or "").strip()
    if len(cleaned) < 2:
        return ScreenView(
            text="⚠️ Название слишком короткое. Введите название категории (2–64 символа):",
            keyboard=cancel_keyboard(),
        ).with_state(
            Screen.TX_CATEGORY, type=type_, amount=ctx.state.get("amount"),
            creating_category=True,
        )
    return await create_category_and_return(ctx, cleaned, type_)

