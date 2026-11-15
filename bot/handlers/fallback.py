"""Обработчик по умолчанию и служебные события.

Отвечает, когда бот не понял запрос, и логирует системные события
(запуск/остановка бота пользователем).
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import help_screen, main_menu_screen
from bot.utils.ui.screen import ScreenView

logger = logging.getLogger(__name__)

UNKNOWN_TEXT = (
    "Не понял запрос. Вот что можно сделать:\n\n"
    "• написать операцию: <i>«Потратил 1250 на продукты»</i>;\n"
    "• добавить расход или доход кнопками;\n"
    "• открыть баланс, историю или статистику.\n\n"
    "Если нужна подсказка — раздел «Помощь»."
)


def unknown_screen() -> ScreenView:
    keyboard = Keyboard()
    keyboard.row(
        callback_button("💸 Расход", "tx:new", "expense"),
        callback_button("💰 Доход", "tx:new", "income"),
    )
    keyboard.row(
        callback_button("📊 Баланс", "balance:show"),
        callback_button("❓ Помощь", "help:show"),
    )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))
    view = ScreenView(text=UNKNOWN_TEXT, keyboard=keyboard)
    return view


async def fallback_handler(ctx: Context) -> ScreenView:
    """Ответ на нераспознанный запрос."""
    if ctx.event == "callback":
        logger.info("Неизвестный callback: %r", ctx.text)
    elif ctx.event == "command":
        logger.info("Неизвестная команда: %r", ctx.text[:40])
    return unknown_screen()


@router.event("bot_stopped")
async def bot_stopped(ctx: Context) -> None:
    """Пользователь остановил бота — просто фиксируем в логе."""
    logger.info("Пользователь %s остановил бота", ctx.max_user_id)
    return None


@router.event("dialog_removed")
async def dialog_removed(ctx: Context) -> None:
    logger.info("Пользователь %s удалил диалог", ctx.max_user_id)
    return None


@router.callback("balance:show")
async def balance_shortcut(ctx: Context) -> ScreenView:
    """Быстрый переход к балансу из служебных экранов."""
    from bot.handlers.analytics import balance_screen

    return await balance_screen(ctx)


__all__ = ["balance_shortcut", "bot_stopped", "dialog_removed", "fallback_handler", "help_screen",
           "main_menu_screen", "unknown_screen"]
