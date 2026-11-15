"""Сценарий «текст → операция»: AI-парсинг, лимиты, подтверждение (ТЗ п. 3.3, 5).

Порядок действий:

1. Проверяем лимит AI (до вызова модели).
2. Вызываем LLM, валидируем ответ (Python-проверка сумм/категорий).
3. Показываем пользователю, что распознано, и просим подтверждение.
4. Списываем AI-запрос **только после успешного ответа модели**
   (при ошибке провайдера запрос не тратится).
5. Записываем операцию в БД только после нажатия «Сохранить».
"""

from __future__ import annotations

import logging

from bot.constants import CATEGORY_EMOJI, EXPENSE, INCOME, SOURCE_TEXT
from bot.context import Context
from bot.services.ai_base import (
    AIError,
    AINotConfiguredError,
    AIUsage,
    AIUsageLogger,
    estimate_llm_cost,
)
from bot.services.ai_limits import AILimitService
from bot.services.ai_schema import ParsedOperation, ParserError, parse_operations
from bot.services.llm_provider import build_provider
from bot.states import Screen
from bot.utils.dates import today_in_tz
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_date_ru

logger = logging.getLogger(__name__)


def ai_limit_text(remaining: int, free_limit: int) -> str:
    """Пояснение о лимите AI, когда он исчерпан."""
    return (
        "Исчерпан бесплатный лимит AI-запросов "
        f"({free_limit}).\n\n"
        "Базовые функции работают без ограничений: можно добавлять расходы "
        "и доходы кнопками, смотреть баланс, историю, статистику, бюджеты и цели.\n\n"
        "AI-функции (разбор текста, голосовой ввод, AI-помощник) доступны по подписке."
    )


async def try_parse_operation(ctx: Context, message: str) -> list[ScreenView]:
    """Разобрать текст через LLM и показать подтверждение."""
    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    allowed, status = await limits.can_use(ctx.user.id)
    if not allowed:
        view = main_menu_screen(
            ai_limit_text(status.remaining, status.free_limit)
        )
        view.keyboard.row(callback_button("💳 Оформить подписку", "ai:subscribe"))
        return [view]

    if not ctx.settings.llm_configured:
        # Ключ не настроен — не тратим лимит, объясняем и подсказываем кнопки.
        view = main_menu_screen(
            "AI-функции пока не подключены (не задан ключ AI Dostup в настройках).\n\n"
            "Записать операцию можно кнопками: «Добавить расход» или «Добавить доход»."
        )
        return [view]

    expense_categories = [
        item.name for item in await ctx.categories.list_for_user(ctx.user.id, EXPENSE)
    ]
    income_categories = [item.name for item in await ctx.categories.list_for_user(ctx.user.id, INCOME)]

    provider = build_provider(ctx.settings)
    usage_logger = AIUsageLogger(ctx.db)
    try:
        parsed = await parse_operations(
            provider,
            message,
            expense_categories=expense_categories,
            income_categories=income_categories,
            today=today_in_tz(ctx.user.timezone),
        )
    except (AIError, AINotConfiguredError, ParserError) as exc:
        logger.warning("AI-парсинг не удался для %r: %s", message[:80], exc)
        await usage_logger.log(
            AIUsage(
                user_id=ctx.user.id,
                request_type="parse",
                provider=provider.name,
                model_used=ctx.settings.ai_dostup_model,
                success=False,
                error_message=str(exc),
            )
        )
        view = main_menu_screen(
            "⚠️ Не удалось распознать операцию (AI временно недоступен).\n"
            "Запрос не списан с лимита.\n\n"
            "Попробуйте ещё раз или добавьте операцию кнопками."
        )
        return [view]

    # Успешный ответ модели — списываем один AI-запрос.
    await limits.consume(ctx.user.id)
    await usage_logger.log(
        AIUsage(
            user_id=ctx.user.id,
            request_type="multi" if len(parsed.operations) > 1 else "parse",
            provider=provider.name,
            model_used=ctx.settings.ai_dostup_model,
            prompt_tokens=None,
            completion_tokens=None,
            cost_usd=estimate_llm_cost(None, None),
        )
    )

    if len(parsed.operations) == 1:
        return [await build_ai_confirm_view(ctx, parsed.operations[0], message)]
    return [await build_ai_multi_view(ctx, parsed.operations, message)]


async def resolve_category_id(ctx: Context, operation: ParsedOperation) -> int | None:
    """Найти категорию по названию или создать новую (ТЗ п. 3.5)."""
    type_ = operation.type
    name = (operation.category or "").strip()
    if not name:
        from bot.constants import EXPENSE_FALLBACK_CATEGORY, INCOME_FALLBACK_CATEGORY

        name = EXPENSE_FALLBACK_CATEGORY if type_ == EXPENSE else INCOME_FALLBACK_CATEGORY

    existing = await ctx.categories.find_by_name(ctx.user.id, type_, name)
    if existing:
        return existing.id
    created = await ctx.categories.create(ctx.user.id, name[:64], type_)
    return created.id if created else None


def _operation_lines(operation: ParsedOperation, currency: str) -> list[str]:
    amount_text = format_money(operation.amount, currency=operation.currency or currency)
    emoji = CATEGORY_EMOJI.get(operation.category, "•")
    title = "Расход" if operation.type == EXPENSE else "Доход"
    lines = [
        f"{title}: <b>{escape_html(amount_text)}</b>",
        f"Категория: {emoji} {escape_html(operation.category or 'Другое')}",
        f"Дата: {format_date_ru(operation.operation_date) if operation.operation_date else '—'}",
    ]
    if operation.comment:
        lines.append(f"Комментарий: {escape_html(operation.comment)}")
    return lines


async def build_ai_confirm_view(
    ctx: Context, operation: ParsedOperation, source_text: str
) -> ScreenView:
    """Экран подтверждения распознанной операции."""
    await resolve_category_id(ctx, operation)
    lines = ["🤖 <b>Понял так:</b>", *_operation_lines(operation, ctx.user.currency)]
    keyboard = Keyboard().row(callback_button("✅ Записать", "ai:save", "0"))
    keyboard.row(
        callback_button("💸 Это расход", "ai:fix_type", "expense"),
        callback_button("💰 Это доход", "ai:fix_type", "income"),
    )
    keyboard.row(callback_button("✖️ Отмена", "menu:main"))

    payload_ops = [operation.model_dump(mode="json")]
    return ScreenView(text="\n".join(lines), keyboard=keyboard).with_state(
        Screen.FREE_INPUT,
        source="ai",
        operations=payload_ops,
        raw_text=source_text[:600],
        source_kind=SOURCE_TEXT,
    )


async def build_ai_multi_view(
    ctx: Context, operations: list[ParsedOperation], source_text: str
) -> ScreenView:
    """Экран подтверждения нескольких операций из одного сообщения."""
    lines = [f"🤖 <b>Нашёл операций: {len(operations)}</b>", ""]
    for index, operation in enumerate(operations, start=1):
        lines.append(f"<b>{index}.</b> " + "; ".join(
            part.replace("<b>", "").replace("</b>", "")
            for part in _operation_lines(operation, ctx.user.currency)
        ))
    lines.append("")
    lines.append("Записать все операции?")

    keyboard = Keyboard().row(callback_button("✅ Записать все", "ai:save", "all"))
    keyboard.row(callback_button("✖️ Отмена", "menu:main"))
    return ScreenView(text="\n".join(lines), keyboard=keyboard).with_state(
        Screen.FREE_INPUT,
        source="ai",
        operations=[operation.model_dump(mode="json") for operation in operations],
        raw_text=source_text[:600],
        source_kind=SOURCE_TEXT,
    )


