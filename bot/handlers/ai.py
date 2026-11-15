"""Обработчики AI-сценариев: подтверждение, запись, помощник.

Ключевой принцип ТЗ: AI распознаёт и объясняет, но данные изменяет только
Python-код — после валидации и явного подтверждения пользователем.
"""

from __future__ import annotations

import logging

from bot.constants import CATEGORY_EMOJI, EXPENSE, INCOME
from bot.context import Context
from bot.router import router
from bot.services.ai_limits import AILimitService
from bot.services.ai_parser import ai_limit_text, resolve_category_id
from bot.services.ai_schema import ParsedOperation
from bot.services.transactions import TransactionError, TransactionService
from bot.states import Screen
from bot.utils.money import format_money
from bot.utils.ui.keyboards import Keyboard, callback_button
from bot.utils.ui.menu import back_to_menu_keyboard, main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html, format_date_ru

logger = logging.getLogger(__name__)


@router.callback("ai:save")
async def ai_save(ctx: Context) -> ScreenView:
    """Записать распознанные операции после подтверждения."""
    raw_operations = ctx.state.get("operations") or []
    if not raw_operations:
        return main_menu_screen("⚠️ Нечего записывать: операция не найдена. Начните заново.")

    source_text = str(ctx.state.get("raw_text") or "")[:600]
    service = TransactionService(ctx.db)
    saved = []
    try:
        for raw in raw_operations:
            operation = ParsedOperation.model_validate(raw)
            category_id = await resolve_category_id(ctx, operation)
            record = await service.create(
                user_id=ctx.user.id,
                type_=operation.type,
                amount=operation.amount,
                currency=operation.currency or ctx.user.currency,
                category_id=category_id,
                transaction_date=operation.operation_date,
                comment=operation.comment,
                source="text",
                raw_text=source_text,
                tz_name=ctx.user.timezone,
            )
            saved.append(record)
    except (TransactionError, ValueError) as exc:
        logger.warning("Не удалось записать AI-операцию: %s", exc)
        await ctx.states.reset(ctx.user.id)
        return main_menu_screen(f"⚠️ {escape_html(str(exc))}\n\nВозвращаемся в меню.")

    await ctx.states.reset(ctx.user.id)

    if len(saved) == 1:
        record = saved[0]
        emoji = CATEGORY_EMOJI.get(record.category_name, "•")
        text = (
            f"✅ <b>{record.type_label} записан</b>\n\n"
            f"Сумма: <b>{escape_html(format_money(record.amount, currency=record.currency))}</b>\n"
            f"Категория: {emoji} {escape_html(record.category_name)}\n"
            f"Дата: {format_date_ru(record.transaction_date)}"
        )
        if record.comment:
            text += f"\nКомментарий: {escape_html(record.comment)}"
    else:
        from decimal import Decimal

        total_expense = sum(
            (r.amount for r in saved if r.type == EXPENSE), start=Decimal("0.00")
        )
        total_income = sum(
            (r.amount for r in saved if r.type == INCOME), start=Decimal("0.00")
        )
        text = f"✅ <b>Записано операций: {len(saved)}</b>\n\n"
        for record in saved:
            text += (
                f"• {record.sign_symbol} "
                f"{escape_html(format_money(record.amount, currency=record.currency))} — "
                f"{escape_html(record.category_name)}\n"
            )
        text += (
            f"\nРасходы: {escape_html(format_money(total_expense, currency=ctx.user.currency))}"
            f"\nДоходы: {escape_html(format_money(total_income, currency=ctx.user.currency))}"
        )

    from bot.services.budget_alerts import append_budget_alerts

    for record in saved:
        text += await append_budget_alerts(ctx, record)

    return main_menu_screen(text)


@router.callback("ai:fix_type")
async def ai_fix_type(ctx: Context) -> ScreenView:
    """Пользователь поправил тип операции (расход ↔ доход)."""
    new_type = ctx.arg if ctx.arg in {EXPENSE, INCOME} else EXPENSE
    raw_operations = ctx.state.get("operations") or []
    if not raw_operations:
        return main_menu_screen("⚠️ Операция не найдена. Начните заново.")

    from bot.constants import EXPENSE_FALLBACK_CATEGORY, INCOME_FALLBACK_CATEGORY
    from bot.services.ai_parser import build_ai_confirm_view

    operation = ParsedOperation.model_validate(raw_operations[0])
    fallback = EXPENSE_FALLBACK_CATEGORY if new_type == EXPENSE else INCOME_FALLBACK_CATEGORY
    existing = await ctx.categories.find_by_name(ctx.user.id, new_type, operation.category)
    fixed = operation.model_copy(
        update={"type": new_type, "category": existing.name if existing else fallback}
    )
    return await build_ai_confirm_view(ctx, fixed, str(ctx.state.get("raw_text") or ""))


@router.callback("ai:open")
@router.command("/ai")
async def ai_menu(ctx: Context) -> ScreenView:
    """Экран AI-функций с остатком лимита (ТЗ п. 5.3)."""
    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    status = await limits.status(ctx.user.id)

    if status.subscription_active:
        limit_line = "Подписка активна — AI-запросы без ограничений"
        if status.subscription_until:
            limit_line += f" до {status.subscription_until:%d.%m.%Y}."
        else:
            limit_line += "."
    else:
        limit_line = (
            f"Бесплатных AI-запросов осталось: <b>{status.remaining}</b> из {status.free_limit}."
        )

    text = (
        "<b>🤖 AI-помощник</b>\n\n"
        "Что умеет AI:\n"
        "• понимать фразы: <i>«Потратил 1250 на продукты»</i>, <i>«Зарплата 85к»</i>;\n"
        "• разбирать несколько операций из одного сообщения;\n"
        "• распознавать голосовые сообщения;\n"
        "• отвечать на вопросы о ваших финансах.\n\n"
        f"{limit_line}"
    )

    keyboard = Keyboard().row(callback_button("💬 Спросить AI", "ai:ask"))
    keyboard.row(callback_button("🎤 Голосовой ввод", "ai:voice_help"))
    if not status.subscription_active:
        keyboard.row(callback_button("💳 Подписка на AI", "ai:subscribe"))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.AI_MENU
    view.state_data = {}
    return view


@router.callback("ai:voice_help")
async def ai_voice_help(ctx: Context) -> ScreenView:
    text = (
        "<b>Голосовой ввод</b>\n\n"
        "Отправьте боту голосовое сообщение — он распознает речь и разберёт "
        "операцию так же, как обычный текст.\n\n"
        "Работает модель <code>gpt-4o-transcribe</code>. При сетевой ошибке "
        "запрос повторяется автоматически.\n\n"
        "Голосовой ввод расходует один AI-запрос: распознавание и разбор текста "
        "считаются вместе. Если распознать не удалось — запрос не списывается."
    )
    view = ScreenView(text=text, keyboard=back_to_menu_keyboard())
    view.next_screen = Screen.AI_MENU
    return view


@router.callback("ai:ask")
async def ai_ask(ctx: Context) -> ScreenView:
    """Перейти в режим вопросов AI-помощнику."""
    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    allowed, status = await limits.can_use(ctx.user.id)
    if not allowed:
        view = main_menu_screen(ai_limit_text(status.remaining, status.free_limit))
        view.keyboard.row(callback_button("💳 Оформить подписку", "ai:subscribe"))
        return view

    view = ScreenView(
        text=(
            "<b>💬 AI-помощник</b>\n\n"
            "Напишите вопрос о ваших финансах, например:\n"
            "• «На что я больше всего тратил в этом месяце?»\n"
            "• «Как сэкономить на продуктах?»\n"
            "• «Хватает ли мне денег до конца месяца?»"
        ),
        keyboard=Keyboard().row(callback_button("🏠 Главное меню", "menu:main")),
    )
    return view.with_state(Screen.AI_ASSISTANT)


ASSISTANT_SYSTEM_PROMPT = """Ты — AI-финансовый помощник в боте учёта личных финансов.
Отвечай кратко (до 1200 символов), по-русски, дружелюбно и по делу.
Используй данные пользователя, приведённые ниже. Не выдумывай цифры: если данных
нет, так и скажи. Не давай юридических или инвестиционных гарантий.
Все расчёты уже сделаны программой — твоя задача объяснить их и подсказать.

Данные пользователя:
{context}
"""


async def ask_assistant(ctx: Context, question: str) -> str:
    """Задать вопрос AI-помощнику с контекстом финансов пользователя."""
    from bot.services.ai_base import AIUsage, AIUsageLogger, estimate_llm_cost
    from bot.services.llm_provider import build_provider
    from bot.services.statistics import StatisticsService
    from bot.utils.dates import current_period, month_range, previous_period
    from bot.utils.money import format_money

    safe_question = " ".join((question or "").split())[:600]
    stats = StatisticsService(ctx.db)
    today_range = month_range(ctx.user.timezone)
    totals = await stats.totals(ctx.user.id, today_range)
    lifetime = await stats.lifetime_totals(ctx.user.id)
    by_category = await stats.expense_by_category(ctx.user.id, today_range)
    prev = await stats.totals_by_period(ctx.user.id, previous_period(current_period(ctx.user.timezone)))

    lines = [
        f"Валюта: {ctx.user.currency}",
        f"Период: {today_range.label}",
        f"Доходы за период: {format_money(totals.income, currency=ctx.user.currency, with_currency=False)}",
        f"Расходы за период: {format_money(totals.expense, currency=ctx.user.currency, with_currency=False)}",
        f"Баланс за период: {format_money(totals.balance, currency=ctx.user.currency, with_currency=False)}",
        f"Доходы за предыдущий месяц: {format_money(prev.income, currency=ctx.user.currency, with_currency=False)}",
        f"Расходы за предыдущий месяц: {format_money(prev.expense, currency=ctx.user.currency, with_currency=False)}",
        f"Всего за всё время: доходы {format_money(lifetime.income, with_currency=False)}, "
        f"расходы {format_money(lifetime.expense, with_currency=False)}",
        "Топ расходных категорий:",
    ]
    for item in by_category[:7]:
        lines.append(
            f"- {item.name}: {format_money(item.total, with_currency=False)} "
            f"({item.share:.0f}%, операций: {item.count})"
        )
    if not by_category:
        lines.append("- за период расходов нет")

    provider = build_provider(ctx.settings)
    usage_logger = AIUsageLogger(ctx.db)
    messages = [
        {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT.format(context="\n".join(lines))},
        {"role": "user", "content": f"<<<ВОПРОС>>>\n{safe_question}"},
    ]
    try:
        result = await provider.complete(messages, temperature=0.3, max_tokens=700)
    except Exception as exc:
        await usage_logger.log(
            AIUsage(
                user_id=ctx.user.id,
                request_type="assistant",
                provider=provider.name,
                model_used=ctx.settings.ai_dostup_model,
                success=False,
                error_message=str(exc)[:500],
            )
        )
        raise

    await usage_logger.log(
        AIUsage(
            user_id=ctx.user.id,
            request_type="assistant",
            provider=provider.name,
            model_used=result.model,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            latency_ms=result.latency_ms,
            cost_usd=estimate_llm_cost(result.prompt_tokens, result.completion_tokens),
        )
    )
    return (result.content or "").strip()[:2000] or "Не удалось сформулировать ответ."


