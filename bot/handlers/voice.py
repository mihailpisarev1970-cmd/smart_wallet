"""Голосовой ввод: аудио → STT → та же логика, что для текста (ТЗ п. 4).

Правила:
* один AI-запрос за цикл «STT + LLM» (счётчик увеличивается один раз);
* если обе STT-модели не справились — лимит не списывается;
* каждый вызов STT логируется в ``ai_usage_log`` (модель, длительность, успех).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from bot.context import Context
from bot.router import router
from bot.services.ai_base import (
    AIError,
    AINotConfiguredError,
    AIUsage,
    AIUsageLogger,
    estimate_stt_cost,
)
from bot.services.ai_limits import AILimitService
from bot.services.ai_parser import ai_limit_text
from bot.services.stt_provider import _extension_from_url, build_provider
from bot.update_parser import (
    find_voice_attachment,
    voice_duration,
    voice_transcription,
    voice_url,
)
from bot.utils.ui.keyboards import callback_button
from bot.utils.ui.menu import main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


async def _route(ctx: Context, text: str) -> list[ScreenView]:
    """Направить распознанный текст в нужный обработчик.

    Голосовое может быть и операцией («потратил 1250 на кофе»), и вопросом
    («какие у меня расходы в этом месяце?»). Раньше всё уходило в парсер
    операций, и вопросы падали с «Не удалось распознать операцию».
    """
    from bot.handlers.free_text import route_free_input

    return await route_free_input(ctx, text)


@router.voice
async def handle_voice(ctx: Context) -> list[ScreenView]:
    """Обработать голосовое сообщение или аудиофайл."""
    attachment = find_voice_attachment(ctx.attachments)
    if attachment is None:
        return [main_menu_screen("⚠️ Не нашёл аудио во вложении. Отправьте голосовое сообщение.")]

    # MAX умеет сам расшифровывать голосовые — используем бесплатный текст,
    # если он пришёл вместе с вложением.
    ready_text = voice_transcription(attachment)

    url = voice_url(attachment)
    if not ready_text and not url:
        return [main_menu_screen("⚠️ Не удалось получить ссылку на аудиофайл.")]

    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    allowed, status = await limits.can_use(ctx.user.id)
    if not allowed:
        view = main_menu_screen(ai_limit_text(status.remaining, status.free_limit))
        view.keyboard.row(callback_button("💳 Оформить подписку", "ai:subscribe"))
        return [view]

    duration = voice_duration(attachment)

    # Статус отправляем СРАЗУ, до скачивания и конвертации: пользователь
    # должен увидеть реакцию на голосовое немедленно.
    status_id = await ctx.send_status("🎤 Распознаю речь…")
    if ready_text:
        logger.info("Голосовое: используем транскрипцию MAX: %r", ready_text[:120])
        views = await _route(ctx, ready_text)
        prefix = f"🎤 <b>Распознано</b> (MAX):\n<i>{escape_html(ready_text)}</i>\n\n"
        for view in views:
            view.text = prefix + view.text
        if status_id and views:
            await ctx.update_status(status_id, views[0].text)
            return views[1:]
        await ctx.delete_status(status_id)
        return views

    if not ctx.settings.stt_configured:
        await ctx.delete_status(status_id)
        return [
            main_menu_screen(
                "Голосовой ввод пока не подключён (не задан ключ STT в настройках).\n\n"
                "Можно написать операцию текстом: <i>«Потратил 1250 на продукты»</i>."
            )
        ]

    try:
        audio = await ctx.api.download_attachment(url)
    except Exception as exc:
        logger.warning("Не удалось скачать голосовое: %s", exc)
        await ctx.delete_status(status_id)
        return [
            main_menu_screen(
                "⚠️ Не удалось скачать голосовое сообщение из MAX.\n"
                "Запрос не списан с лимита.\n\n"
                "Попробуйте отправить ещё раз или напишите текстом: "
                "<i>«Потратил 1250 на продукты»</i>."
            )
        ]
    filename = f"voice.{_extension_from_url(url)}"

    provider = build_provider(ctx.settings)
    usage_logger = AIUsageLogger(ctx.db)
    try:
        result = await provider.transcribe(
            audio,
            filename,
        )
    except (AIError, AINotConfiguredError) as exc:
        logger.warning("STT не удался: %s", exc)
        await usage_logger.log(
            AIUsage(
                user_id=ctx.user.id,
                request_type="stt",
                provider=provider.name,
                model_used=ctx.settings.stt_primary_model,
                success=False,
                audio_duration_seconds=Decimal(str(duration)) if duration else None,
                error_message=str(exc)[:500],
            )
        )
        await ctx.delete_status(status_id)
        return [
            main_menu_screen(
                "⚠️ Не удалось распознать голосовое сообщение.\n"
                "Запрос не списан с лимита.\n\n"
                "Попробуйте записать ещё раз или напишите текстом."
            )
        ]

    await usage_logger.log(
        AIUsage(
            user_id=ctx.user.id,
            request_type="stt",
            provider=provider.name,
            model_used=result.model,
            success=True,
            audio_duration_seconds=Decimal(str(duration)) if duration else None,
            latency_ms=result.latency_ms,
            fallback_used=result.fallback_used,
            cost_usd=estimate_stt_cost(duration),
        )
    )
    logger.info(
        "STT (%s): %r%s",
        result.model,
        result.text[:120],
        " [fallback]" if result.fallback_used else "",
    )

    # Показываем распознанный текст и переключаемся на разбор: LLM отвечает
    # ~10 секунд, пользователь видит прогресс вместо «зависшего» статуса.
    if status_id:
        await ctx.update_status(
            status_id,
            f"🎤 <b>Распознано</b>:\n<i>{escape_html(result.text)}</i>\n\n"
            "🤖 Обрабатываю…",
        )

    views = await _route(ctx, result.text)
    prefix = (
        f"🎤 <b>Распознано</b> ({escape_html(result.model)}):\n"
        f"<i>{escape_html(result.text)}</i>\n\n"
    )
    for view in views:
        view.text = prefix + view.text

    # Статусное сообщение заменяем первым экраном результата — пользователь
    # не видит «висящего» «Распознаю…» и не получает лишнего сообщения.
    if status_id and views:
        await ctx.update_status(status_id, views[0].text)
        return views[1:]

    await ctx.delete_status(status_id)
    return views
