"""Настройки пользователя (ТЗ п. 3.11).

Смена валюты и часового пояса, уведомления, категории, экспорт данных
и удаление аккаунта со всеми данными.
"""

from __future__ import annotations

import logging

from bot.constants import POPULAR_TIMEZONES
from bot.context import Context
from bot.router import router
from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


async def settings_menu_view(ctx: Context, *, notice: str = "") -> ScreenView:
    """Главный экран настроек."""
    lines = []
    if notice:
        lines.extend([notice, ""])
    lines.extend(
        [
            "<b>⚙️ Настройки</b>",
            "",
            f"Валюта: <b>{ctx.user.currency}</b>",
            f"Часовой пояс: <b>{escape_html(ctx.user.timezone)}</b>",
            f"Уведомления о бюджете: <b>{'вкл' if ctx.user.notifications_enabled else 'выкл'}</b>",
        ]
    )

    keyboard = Keyboard().row(
        callback_button("💱 Валюта", "settings:currency"),
        callback_button("🕒 Часовой пояс", "settings:timezone"),
    )
    keyboard.row(
        callback_button(
            f"🔔 Уведомления: {'вкл' if ctx.user.notifications_enabled else 'выкл'}",
            "settings:notifications",
        ),
        callback_button("🏷 Категории", "cat:open"),
    )
    keyboard.row(callback_button("📤 Экспорт CSV/Excel", "export:menu"))
    keyboard.row(callback_button("🗑 Удалить аккаунт", "settings:delete_account"))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.SETTINGS_MENU
    view.state_data = {}
    return view


@router.callback("settings:open")
@router.command("/settings")
async def settings_menu(ctx: Context) -> ScreenView:
    """Открыть настройки."""
    return await settings_menu_view(ctx)


@router.callback("settings:currency")
async def settings_currency(ctx: Context) -> ScreenView:
    """Выбор валюты."""
    keyboard = Keyboard().row(
        callback_button("₽ Рубль", "settings:set_currency", "RUB"),
        callback_button("$ Доллар", "settings:set_currency", "USD"),
        callback_button("€ Евро", "settings:set_currency", "EUR"),
    )
    keyboard.row(callback_button("« Назад", "settings:open"))
    view = ScreenView(text="<b>Выберите основную валюту:</b>", keyboard=keyboard)
    view.next_screen = Screen.SETTINGS_CURRENCY
    return view


@router.callback("settings:set_currency")
async def settings_set_currency(ctx: Context) -> ScreenView:
    currency = ctx.arg.upper()
    if currency not in {"RUB", "USD", "EUR"}:
        return await settings_menu_view(ctx, notice="⚠️ Неизвестная валюта.")
    await ctx.users.update_settings(ctx.user.id, currency=currency)
    return await settings_menu_view(ctx, notice=f"✅ Валюта изменена на {currency}.")


@router.callback("settings:timezone")
async def settings_timezone(ctx: Context) -> ScreenView:
    """Выбор часового пояса."""
    keyboard = Keyboard()
    buttons = [
        callback_button(label, "settings:set_timezone", tz) for tz, label in POPULAR_TIMEZONES
    ]
    keyboard.add(*buttons, per_row=2)
    keyboard.row(callback_button("« Назад", "settings:open"))
    view = ScreenView(text="<b>Выберите часовой пояс:</b>", keyboard=keyboard)
    view.next_screen = Screen.SETTINGS_TIMEZONE
    return view


@router.callback("settings:set_timezone")
async def settings_set_timezone(ctx: Context) -> ScreenView:
    timezone = ctx.arg
    if not timezone:
        return await settings_menu_view(ctx, notice="⚠️ Часовой пояс не выбран.")
    await ctx.users.update_settings(ctx.user.id, timezone=timezone)
    return await settings_menu_view(ctx, notice=f"✅ Часовой пояс: {escape_html(timezone)}.")


@router.callback("settings:notifications")
async def settings_notifications(ctx: Context) -> ScreenView:
    """Включить/выключить уведомления о бюджете."""
    new_value = not ctx.user.notifications_enabled
    await ctx.users.update_settings(ctx.user.id, notifications_enabled=new_value)
    state = "включены" if new_value else "выключены"
    return await settings_menu_view(ctx, notice=f"✅ Уведомления {state}.")


@router.callback("settings:delete_account")
async def settings_delete_account(ctx: Context) -> ScreenView:
    """Подтверждение удаления аккаунта (ТЗ п. 3.11, 11)."""
    keyboard = Keyboard().row(callback_button("🗑 Удалить всё", "settings:delete_confirm"))
    keyboard.row(callback_button("✖️ Отмена", "settings:open"))
    view = ScreenView(
        text=(
            "<b>Удалить аккаунт?</b>\n\n"
            "Будут удалены все операции, категории, бюджеты, цели и история AI-запросов. "
            "Действие необратимо."
        ),
        keyboard=keyboard,
    )
    view.next_screen = Screen.SETTINGS_DELETE_ACCOUNT
    return view


@router.callback("settings:delete_confirm")
async def settings_delete_confirm(ctx: Context) -> ScreenView:
    """Удалить аккаунт и все данные."""
    await ctx.users.delete_user(ctx.user.id)
    logger.info("Пользователь %s удалил аккаунт", ctx.max_user_id)

    view = ScreenView(
        text=(
            "<b>Аккаунт удалён.</b>\n\n"
            "Все ваши данные удалены. Если захотите вернуться — отправьте /start."
        ),
        keyboard=Keyboard().row(callback_button("🔄 Начать заново", "onboarding:restart")),
    )
    view.next_screen = Screen.MAIN_MENU
    return view


@router.callback("onboarding:restart")
async def onboarding_restart(ctx: Context) -> ScreenView:
    """Пересоздать аккаунт после удаления."""
    from bot.handlers.start import start_handler

    user, _ = await ctx.users.ensure_user(
        ctx.max_user_id, username=ctx.user.username, first_name=ctx.user.first_name
    )
    ctx.user = user
    return await start_handler(ctx)

