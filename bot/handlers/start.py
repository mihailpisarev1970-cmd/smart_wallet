"""Регистрация пользователя, онбординг и главное меню (ТЗ п. 3.1, 3.2).

Сценарий первого запуска:
``/start`` → приветствие → выбор валюты → **главное меню**.
Часовой пояс по умолчанию — ``Europe/Moscow`` (меняется в настройках).
Пока пользователь не выбрал валюту, любые действия ведут в онбординг.
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import (
    MAIN_MENU_TEXT,
    about_screen,
    help_screen,
    main_menu_screen,
    welcome_screen,
)
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


def currency_keyboard() -> Keyboard:
    return Keyboard().row(
        callback_button("₽ Рубль", "onboarding:currency", "RUB"),
        callback_button("$ Доллар", "onboarding:currency", "USD"),
        callback_button("€ Евро", "onboarding:currency", "EUR"),
    )


def timezone_keyboard() -> Keyboard:
    from bot.constants import POPULAR_TIMEZONES

    keyboard = Keyboard()
    buttons = [
        callback_button(label, "onboarding:tz", tz) for tz, label in POPULAR_TIMEZONES[:12]
    ]
    keyboard.add(*buttons, per_row=2)
    keyboard.row(callback_button("🕒 Москва — по умолчанию", "onboarding:tz", "Europe/Moscow"))
    return keyboard


@router.command("/start")
@router.command("/menu")
@router.event("bot_started")
async def start_handler(ctx: Context) -> ScreenView | list[ScreenView]:
    """Первый запуск или возврат в меню."""
    if ctx.user.onboarding_completed:
        return main_menu_screen()

    await ctx.states.set(ctx.user.id, Screen.ONBOARDING_CURRENCY, {})
    view = welcome_screen()
    view.keyboard = Keyboard().row(callback_button("▶️ Начать настройку", "onboarding:start"))
    view.next_screen = Screen.ONBOARDING_CURRENCY
    return view


@router.callback("onboarding:start")
async def onboarding_intro(ctx: Context) -> ScreenView:
    return ScreenView(
        text=(
            "<b>Шаг 1 из 2. Основная валюта</b>\n\n"
            "В какой валюте вы ведёте учёт? Суммы можно будет сменить в настройках."
        ),
        keyboard=currency_keyboard(),
    ).with_state(Screen.ONBOARDING_CURRENCY)


@router.callback("onboarding:currency")
async def onboarding_currency(ctx: Context) -> ScreenView:
    """Выбор валюты завершает настройку — сразу показываем главное меню.

    Часовой пояс по умолчанию ``Europe/Moscow``; его можно изменить
    в «Настройки → Часовой пояс».
    """
    currency = ctx.arg.upper() or "RUB"
    if currency not in {"RUB", "USD", "EUR"}:
        currency = "RUB"

    timezone = ctx.user.timezone or "Europe/Moscow"
    await ctx.users.complete_onboarding(ctx.user.id, currency, timezone)
    await ctx.states.set(ctx.user.id, Screen.MAIN_MENU, {})

    from bot.utils.dates import now_in_tz

    local_now = now_in_tz(timezone)
    logger.info(
        "Онбординг завершён: user=%s currency=%s tz=%s", ctx.user.id, currency, timezone
    )
    return main_menu_screen(
        f"<b>Готово!</b> Валюта: <b>{currency}</b>, часовой пояс: <b>{timezone}</b> "
        f"(изменить можно в настройках).\n"
        f"Сейчас у вас {local_now:%H:%M}, {local_now:%d.%m.%Y}.\n\n"
        + MAIN_MENU_TEXT
    )


@router.callback("onboarding:timezone")
async def onboarding_set_timezone(ctx: Context) -> ScreenView:
    """Смена часового пояса из онбординга (если понадобится)."""
    timezone = ctx.arg or "Europe/Moscow"
    currency = ctx.state.get("currency", ctx.user.currency)
    await ctx.users.complete_onboarding(ctx.user.id, currency, timezone)
    return main_menu_screen(
        f"✅ Часовой пояс: <b>{escape_html(timezone)}</b>.\n\n" + MAIN_MENU_TEXT
    )


@router.callback("menu:main")
@router.command("/cancel")
async def main_menu_handler(ctx: Context) -> ScreenView:
    """Возврат в главное меню (сбрасывает незавершённый черновик)."""
    await ctx.states.set(ctx.user.id, Screen.MAIN_MENU, {})
    return main_menu_screen()


@router.callback("help:show")
@router.command("/help")
async def help_handler(ctx: Context) -> ScreenView:
    return help_screen()


@router.callback("about:show")
@router.command("/about")
async def about_handler(ctx: Context) -> ScreenView:
    """Экран «О проекте» — автор, описание и ссылка для связи."""
    return about_screen()
