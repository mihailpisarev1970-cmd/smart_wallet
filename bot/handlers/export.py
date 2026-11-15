"""Экспорт данных в CSV и Excel (ТЗ п. 3.12).

Доступно бесплатно и без ограничений: пользователь выбирает формат,
бот формирует файл и отправляет его вложением.
"""

from __future__ import annotations

import logging

from bot.context import Context
from bot.router import router
from bot.services.export import ExportService, export_filename
from bot.services.upload import send_with_file, upload_file
from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


@router.callback("export:menu")
async def export_menu(ctx: Context) -> ScreenView:
    """Выбор формата экспорта."""
    keyboard = Keyboard().row(
        callback_button("📄 CSV", "export:csv"),
        callback_button("📊 Excel", "export:excel"),
    )
    keyboard.row(callback_button("« Назад", "settings:open"))
    view = ScreenView(
        text=(
            "<b>📤 Экспорт данных</b>\n\n"
            "Выгружу все ваши операции. CSV удобно открыть в таблицах и Google Sheets, "
            "Excel — для работы с формулами и итогами."
        ),
        keyboard=keyboard,
    )
    view.next_screen = Screen.SETTINGS_EXPORT
    return view


async def _do_export(ctx: Context, fmt: str) -> ScreenView:
    service = ExportService(ctx.db)
    try:
        if fmt == "csv":
            content, count = await service.to_csv(ctx.user.id)
            filename = export_filename("csv")
        else:
            content, count = await service.to_excel(ctx.user.id)
            filename = export_filename("xlsx")
    except Exception as exc:
        logger.exception("Ошибка экспорта: %s", exc)
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen("⚠️ Не удалось сформировать файл. Попробуйте позже.")

    if count == 0:
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen(
            "⚠️ Пока нечего экспортировать: операций нет.\n"
            "Добавьте расход или доход — и попробуйте снова."
        )

    try:
        uploaded = await upload_file(ctx.api, content, filename)
    except Exception as exc:
        logger.exception("Не удалось загрузить файл в MAX: %s", exc)
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen(
            "⚠️ Файл сформирован, но отправить его в MAX не удалось. Попробуйте ещё раз."
        )

    # MAX обрабатывает загруженный файл асинхронно: сразу после загрузки
    # POST /messages отвечает attachment.not.ready. Отправляем отдельным
    # сообщением с повторами, а не как вложение экрана.
    try:
        await send_with_file(
            ctx.api,
            uploaded.attachment(filename),
            text=f"📄 <b>{escape_html(filename)}</b>\nОпераций в файле: {count}",
            chat_id=ctx.chat_id,
            user_id=ctx.max_user_id,
        )
    except Exception as exc:
        logger.exception("Не удалось отправить файл %s: %s", filename, exc)
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen(
            "⚠️ Файл сформирован, но MAX не принял вложение (файл ещё обрабатывается).\n"
            "Попробуйте ещё раз через несколько секунд."
        )

    await ctx.states.reset(ctx.user.id)
    logger.info("Экспорт %s: %s операций, %s байт", fmt, count, len(content))
    view = ScreenView(
        text=(
            f"📤 <b>Экспорт готов</b>\n\n"
            f"Операций в файле: {count}\n"
            "Файл отправлен отдельным сообщением выше."
        ),
        keyboard=Keyboard().row(
            callback_button("📤 Ещё экспорт", "export:menu"),
            callback_button("🏠 Главное меню", "menu:main"),
        ),
    )
    view.next_screen = Screen.SETTINGS_MENU
    return view


@router.callback("export:csv")
async def export_csv(ctx: Context) -> ScreenView:
    return await _do_export(ctx, "csv")


@router.callback("export:excel")
async def export_excel(ctx: Context) -> ScreenView:
    return await _do_export(ctx, "excel")
