"""Экран подписки на AI-функции и запуск оплаты (ТЗ п. 5.3, 6)."""

from __future__ import annotations

import logging
from decimal import Decimal

from bot.context import Context
from bot.router import router
from bot.services.ai_limits import AILimitService
from bot.services.subscription import SubscriptionService
from bot.services.yookassa import YooKassaConfig, build_client
from bot.states import Screen
from bot.utils.ui.keyboards import Keyboard, callback_button, link_button
from bot.utils.ui.menu import main_menu_screen
from bot.utils.ui.screen import ScreenView
from bot.utils.ui.text import escape_html

logger = logging.getLogger(__name__)


def _pay_page_url(ctx: Context, payment_id: str) -> str:
    """Ссылка на брендированную страницу оплаты на домене проекта.

    Если домен не задан (локальная разработка), возвращаем пустую строку —
    вызывающий код подставит прямую ссылку ЮKassa.
    """
    base = (ctx.settings.webhook_base_url or "").rstrip("/")
    if not base:
        return ""
    return f"{base}/pay/{payment_id}"


@router.callback("ai:subscribe")
async def subscribe_screen(ctx: Context) -> ScreenView:
    """Описание подписки и кнопка оплаты."""
    settings = ctx.settings
    price = settings.ai_subscription_price_rub
    days = settings.ai_subscription_days
    limits = AILimitService(ctx.db, settings.ai_free_requests)
    status = await limits.status(ctx.user.id)

    lines = [
        "<b>💳 Подписка на AI-функции</b>",
        "",
        f"Стоимость: <b>{price} ₽</b> за {days} дней.",
        "",
        "Что входит:",
        "• неограниченный разбор текста и голоса;",
        "• несколько операций в одном сообщении;",
        "• AI-помощник по вашим финансам;",
        "• новые AI-функции по мере появления.",
        "",
        "Базовый учёт финансов (кнопки, баланс, история, статистика, бюджеты, цели) "
        "остаётся бесплатным.",
    ]
    if status.subscription_active and status.subscription_until:
        lines.append("")
        lines.append(f"Подписка активна до {status.subscription_until:%d.%m.%Y}.")
    elif not status.subscription_active:
        lines.append("")
        lines.append(f"Бесплатных AI-запросов использовано: {status.used} из {status.free_limit}.")

    keyboard = Keyboard()
    config = YooKassaConfig.from_settings(settings)
    if config.configured:
        keyboard.row(callback_button(f"💳 Оплатить {price} ₽", "subscribe:pay"))
    else:
        lines.append("")
        lines.append(
            "<i>Онлайн-оплата пока не подключена. Напишите владельцу бота — "
            "подписку можно активировать вручную.</i>"
        )
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text="\n".join(lines), keyboard=keyboard)
    view.next_screen = Screen.AI_SUBSCRIPTION
    return view


@router.callback("subscribe:pay")
async def subscribe_pay(ctx: Context) -> ScreenView:
    """Создать платёж в ЮKassa и показать ссылку на оплату."""
    settings = ctx.settings
    config = YooKassaConfig.from_settings(settings)
    if not config.configured:
        return main_menu_screen(
            "⚠️ Онлайн-оплата не настроена. Сообщите владельцу бота."
        )

    client = build_client(settings)
    service = SubscriptionService(ctx.db, client, days=settings.ai_subscription_days)
    amount = Decimal(str(settings.ai_subscription_price_rub))
    try:
        url, payment_id = await service.create_payment(
            ctx.user.id, amount, max_user_id=ctx.max_user_id
        )
    except Exception as exc:
        logger.exception("Не удалось создать платёж ЮKassa: %s", exc)
        return main_menu_screen(
            "⚠️ Не удалось создать платёж. Попробуйте позже или напишите владельцу бота."
        )

    text = (
        "<b>Счёт готов</b>\n\n"
        f"Сумма: <b>{escape_html(str(amount))} ₽</b>\n"
        f"Номер платежа: <code>{escape_html(payment_id[:8])}</code>\n\n"
        "Нажмите кнопку ниже — откроется страница оплаты. "
        "Можно платить картой или через СБП.\n\n"
        "После оплаты подписка активируется автоматически.\n\n"
        "⚠️ <b>ВАЖНО:</b> при оплате отключите VPN."
    )
    pay_page = _pay_page_url(ctx, payment_id) or url
    keyboard = Keyboard().row(link_button("🔗 Перейти к оплате", pay_page))
    keyboard.row(callback_button("✅ Я оплатил", "subscribe:check"))
    keyboard.row(callback_button("🏠 Главное меню", "menu:main"))

    view = ScreenView(text=text, keyboard=keyboard)
    view.next_screen = Screen.AI_SUBSCRIPTION
    return view


@router.callback("subscribe:check")
async def subscribe_check(ctx: Context) -> ScreenView:
    """Проверить статус подписки (оплата подтверждается webhook'ом Robokassa)."""
    limits = AILimitService(ctx.db, ctx.settings.ai_free_requests)
    status = await limits.status(ctx.user.id)
    if status.subscription_active:
        until = f" до {status.subscription_until:%d.%m.%Y}" if status.subscription_until else ""
        return main_menu_screen(f"✅ Подписка активна{until}. AI-запросы без ограничений.")
    return ScreenView(
        text=(
            "Платёж пока не подтверждён.\n\n"
            "Обычно это занимает несколько секунд. Если оплата прошла, "
            "нажмите «Проверить» ещё раз чуть позже."
        ),
        keyboard=Keyboard().row(
            callback_button("🔄 Проверить", "subscribe:check"),
            callback_button("🏠 Главное меню", "menu:main"),
        ),
    )
