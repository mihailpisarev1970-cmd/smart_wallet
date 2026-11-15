"""Обработка свободного текста и голосовых сообщений (ТЗ п. 3.3, 4, 5).

Поток:

1. Голосовое сообщение → STT (gpt-4o-transcribe) → текст.
2. Текст → **определение намерения** (операция или вопрос).
3. Если операция → LLM (DeepSeek через AI Dostup) → структурированный JSON.
   Python валидирует результат (суммы, категории, типы) — только после этого
   бот предлагает подтверждение. AI никогда не записывает данные сам.
4. Если вопрос → AI-помощник отвечает с контекстом финансов пользователя.

Лимит AI: 10 бесплатных запросов (STT + LLM в одном цикле = один запрос),
при активной подписке лимит не применяется (ТЗ п. 5.3, 12).
"""

from __future__ import annotations

import logging
import re

from bot.context import Context
from bot.router import router
from bot.states import Screen
from bot.utils.ui.screen import ScreenView

logger = logging.getLogger(__name__)

#: Признак того, что текст может содержать сумму.
_AMOUNT_HINT = re.compile(r"\d")
_GREETING = re.compile(
    r"^(привет|здравствуй|добрый (день|вечер)|hi|hello|спасибо|ок|окей|хорошо)[!. ]*$",
    re.IGNORECASE,
)

#: Экраны, ввод на которых обрабатывает :mod:`bot.handlers.sequence_input`.
SEQUENCE_SCREENS = frozenset(
    {
        Screen.HISTORY_CUSTOM_FROM,
        Screen.HISTORY_CUSTOM_TO,
        Screen.HISTORY_EDIT_VALUE,
        Screen.BUDGET_AMOUNT,
        Screen.GOAL_NAME,
        Screen.GOAL_TARGET,
        Screen.GOAL_DEADLINE,
        Screen.GOAL_CONTRIBUTE,
        Screen.SETTINGS_CATEGORY_ADD_NAME,
        Screen.SETTINGS_CATEGORY_RENAME,
        Screen.AI_ASSISTANT,
    }
)


def looks_like_operation(text: str) -> bool:
    """Эвристика: не тратить AI-запрос на приветствия и пустой текст."""
    if len(text) < 3 or _GREETING.match(text.strip()):
        return False
    return bool(_AMOUNT_HINT.search(text))


@router.text
async def free_text_handler(ctx: Context) -> list[ScreenView]:
    """Точка входа для сообщений, которые не являются командой.

    Маршрутизация по текущему экрану: если бот ждёт конкретный ввод,
    он трактуется соответствующим образом, иначе — как новая операция.
    """
    screen = ctx.state.screen

    if screen == Screen.TX_AMOUNT:
        from bot.handlers.transactions import handle_amount_input

        return [await handle_amount_input(ctx, ctx.text)]

    if screen == Screen.TX_CATEGORY:
        from bot.handlers.categories import handle_new_category_input

        return [await handle_new_category_input(ctx, ctx.text)]

    if screen == Screen.TX_COMMENT:
        from bot.handlers.transactions import build_confirm_view

        return [await build_confirm_view(ctx, comment=ctx.text.strip()[:500])]

    if screen in SEQUENCE_SCREENS:
        from bot.handlers.sequence_input import handle_sequence_input

        return await handle_sequence_input(ctx, ctx.text)

    return await handle_free_input(ctx, ctx.text)


async def handle_free_input(ctx: Context, message: str) -> list[ScreenView]:
    """Распознать операцию из свободного текста или ответить на вопрос."""
    return await route_free_input(ctx, message)


async def route_free_input(ctx: Context, message: str) -> list[ScreenView]:
    """Определить намерение и направить в нужный обработчик.

    Используется и для текста, и для голоса: логика «операция или вопрос»
    должна быть одинаковой, иначе голосовое «какие у меня расходы?»
    уходило в парсер операций и падало с ошибкой.
    """
    from bot.services.ai_limits import AILimitService
    from bot.services.ai_parser import ai_limit_text, try_parse_operation
    from bot.services.intent import classify_with_llm, detect_intent
    from bot.services.llm_provider import build_provider
    from bot.utils.ui.keyboards import callback_button
    from bot.utils.ui.menu import main_menu_screen

    message = (message or "").strip()
    if not message:
        return []

    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    allowed, status = await limits.can_use(ctx.user.id)
    if not allowed:
        view = main_menu_screen(ai_limit_text(status.remaining, status.free_limit))
        view.keyboard.row(callback_button("💳 Оформить подписку", "ai:subscribe"))
        return [view]

    if not ctx.settings.llm_configured:
        return [
            main_menu_screen(
                "AI-функции пока не подключены (не задан ключ AI Dostup в настройках).\n\n"
                "Записать операцию можно кнопками: «Добавить расход» или «Добавить доход»."
            )
        ]

    # 1. Быстрая эвристика, при неуверенности — уточняем у модели.
    intent = detect_intent(message)
    if intent is None:
        intent = await classify_with_llm(build_provider(ctx.settings), message)
        logger.info("Намерение для %r -> %s (LLM)", message[:60], intent)
    else:
        logger.info("Намерение для %r -> %s (эвристика)", message[:60], intent)

    if intent == "question":
        return await answer_question(ctx, message)

    return await try_parse_operation(ctx, message)


async def answer_question(ctx: Context, question: str) -> list[ScreenView]:
    """Ответить как AI-помощник (с контекстом финансов пользователя)."""
    from bot.handlers.ai import ask_assistant
    from bot.services.ai_base import AIError, AINotConfiguredError
    from bot.services.ai_limits import AILimitService
    from bot.utils.ui.keyboards import Keyboard, callback_button
    from bot.utils.ui.menu import main_menu_screen

    try:
        answer = await ask_assistant(ctx, question)
    except AINotConfiguredError:
        return [
            main_menu_screen(
                "AI-помощник пока не подключён (не задан ключ AI Dostup в настройках)."
            )
        ]
    except AIError as exc:
        logger.warning("AI-помощник недоступен: %s", exc)
        return [
            main_menu_screen(
                "⚠️ AI-помощник временно недоступен. Запрос не списан с лимита.\n"
                "Попробуйте ещё раз чуть позже."
            )
        ]

    # Успешный ответ — списываем один AI-запрос (ТЗ п. 5.3, 12).
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
