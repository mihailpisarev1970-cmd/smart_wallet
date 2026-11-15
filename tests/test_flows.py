"""Сквозные проверки сценариев бота (эмуляция кликов без MAX и без сети).

Тесты используют ту же PostgreSQL-базу, что и бот (она поднята локально),
с отдельным ``max_user_id``. Отключить: ``SKIP_DB_TESTS=1``.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_DB_TESTS") == "1", reason="тесты БД отключены"
)

MAX_USER_ID = 999000222


class FakeAPI:
    """Фейковый MAX-клиент: запоминает отправленные сообщения."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_message(self, **kwargs: Any) -> dict[str, Any]:
        self.sent.append(kwargs)
        return {"message": {"body": {"mid": f"mid.{len(self.sent)}"}}}

    async def answer_callback(self, callback_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"ok": True}

    async def download_attachment(self, url: str) -> bytes:
        return b""


@pytest.fixture()
async def app():
    """Зависимости: реальные репозитории поверх локальной БД + фейковый API."""
    import bot.handlers  # noqa: F401 - регистрирует обработчики
    from bot.config import get_settings
    from bot.db import Database
    from bot.db.states import StateRepository
    from bot.db.users import CategoryRepository, UserRepository

    db = Database(get_settings().database_url, min_size=1, max_size=3)
    await db.connect()
    deps = {
        "db": db,
        "api": FakeAPI(),
        "settings": get_settings(),
        "users": UserRepository(db),
        "categories": CategoryRepository(db),
        "states": StateRepository(db),
    }
    try:
        yield deps
    finally:
        await db.close()


async def make_ctx(app, *, event: str, text: str, args: list[str] | None = None):
    """Собрать контекст так, как это делает диспетчер."""
    from bot.context import Context

    user, _ = await app["users"].ensure_user(
        MAX_USER_ID, username="autotest", first_name="Тест"
    )
    return Context(
        max_user_id=MAX_USER_ID,
        user=user,
        state=await app["states"].get(user.id),
        db=app["db"],
        api=app["api"],
        settings=app["settings"],
        users=app["users"],
        categories=app["categories"],
        states=app["states"],
        event=event,
        text=text,
        args=args or [],
    )


async def click(app, payload: str):
    """Сымитировать нажатие кнопки: разобрать payload и вызвать роутер."""
    from bot.router import router
    from bot.update_parser import parse_payload

    action, args = parse_payload(payload)
    ctx = await make_ctx(app, event="callback", text=action, args=args)
    return ctx, await router.dispatch(ctx)


def texts(views) -> str:
    return "\n".join(view.text for view in views)


def button_payloads(views) -> list[str]:
    return [
        button.payload
        for view in views
        for row in view.keyboard.rows
        for button in row
        if button.payload
    ]


async def test_onboarding_currency_goes_straight_to_main_menu(app) -> None:
    """После выбора валюты сразу показывается главное меню со всеми кнопками."""
    from bot.handlers.start import start_handler

    ctx = await make_ctx(app, event="command", text="/start")
    await start_handler(ctx)

    _ctx, views = await click(app, "onboarding:currency:RUB")
    assert views, "бот не ответил на выбор валюты"
    assert "Главное меню" in texts(views)

    payloads = button_payloads(views)
    for expected in (
        "tx:new:expense",
        "tx:new:income",
        "balance:show",
        "history:open",
        "stats:open",
        "budget:open",
        "goals:open",
        "ai:open",
        "settings:open",
        "help:show",
    ):
        assert expected in payloads, f"в меню нет кнопки {expected}"

    user = await app["users"].get_by_max_id(MAX_USER_ID)
    assert user is not None and user.onboarding_completed and user.currency == "RUB"


async def test_main_menu_buttons_all_respond(app) -> None:
    """Каждая кнопка главного меню открывает свой экран, а не «не понял»."""
    from bot.utils.ui.menu import main_menu_keyboard

    payloads = [
        button.payload
        for row in main_menu_keyboard().rows
        for button in row
        if button.payload
    ]
    for payload in payloads:
        _ctx, views = await click(app, payload)
        assert views, f"кнопка {payload} не дала ответа"
        assert "Не понял запрос" not in texts(views), f"кнопка {payload} в fallback"


async def test_settings_has_no_stt_model_choice(app) -> None:
    """В настройках больше нет выбора STT-модели: whisper-1 у провайдера нет."""
    _ctx, views = await click(app, "settings:open")
    payloads = button_payloads(views)
    assert "settings:stt" not in payloads
    assert not any(p.startswith("settings:set_stt") for p in payloads)
    assert "Модель распознавания" not in texts(views)
    # Остальные настройки на месте
    for expected in ("settings:currency", "settings:timezone", "settings:notifications"):
        assert expected in payloads, f"в настройках нет кнопки {expected}"


async def test_about_screen(app) -> None:
    """Кнопка «О проекте» открывает экран с автором и кликабельной ссылкой."""
    from bot.utils.ui.menu import ABOUT_CONTACT_URL

    _ctx, views = await click(app, "about:show")
    body = texts(views)
    assert "О проекте" in body
    assert "Михаил" in body
    assert "Умный кошелёк" in body
    assert "напишите мне" in body
    # Ссылка-визитка для связи; max.ru/<user_id> MAX не поддерживает
    assert ABOUT_CONTACT_URL == "https://golnk.ru/pbB0G"

    buttons = [b for view in views for row in view.keyboard.rows for b in row]
    links = [b for b in buttons if b.type == "link"]
    assert links, "нет кнопки-ссылки для связи"
    assert links[0].url == ABOUT_CONTACT_URL
    assert links[0].text == "💬 Написать Михаилу"


async def test_add_expense_by_buttons(app) -> None:
    """Расход → сумма → категория → подтверждение → запись в БД."""
    from decimal import Decimal

    from bot.handlers.transactions import handle_amount_input
    from bot.services.statistics import StatisticsService
    from bot.utils.dates import today_range

    _ctx, views = await click(app, "tx:new:expense")
    assert "Новый расход" in texts(views)

    ctx = await make_ctx(app, event="message", text="1250,50")
    views = [await handle_amount_input(ctx, "1250,50")]
    assert "Выберите категорию" in texts(views)

    category_payload = next((p for p in button_payloads(views) if p.startswith("tx:cat:")), None)
    assert category_payload, "нет кнопок категорий"

    _ctx, views = await click(app, category_payload)
    _ctx, views = await click(app, "tx:comment_skip")
    assert "Проверьте расход" in texts(views)

    _ctx, views = await click(app, "tx:save")
    assert "Расход записан" in texts(views)

    user = await app["users"].get_by_max_id(MAX_USER_ID)
    totals = await StatisticsService(app["db"]).totals(user.id, today_range(user.timezone))
    assert totals.expense >= Decimal("1250.50")


async def test_balance_and_statistics_render(app) -> None:
    _ctx, views = await click(app, "balance:show")
    assert "Мой баланс" in texts(views)
    _ctx, views = await click(app, "stats:show:month")
    assert "Статистика" in texts(views)


async def test_history_and_delete_requires_confirmation(app) -> None:
    """История показывает операции; удаление — только после подтверждения."""
    from bot.handlers.history import show_period
    from bot.utils.dates import today_range

    ctx = await make_ctx(app, event="callback", text="history:period", args=["today"])
    user = await app["users"].get_by_max_id(MAX_USER_ID)
    view = await show_period(ctx, today_range(user.timezone))
    assert "История" in view.text

    item_payloads = [
        button.payload
        for row in view.keyboard.rows
        for button in row
        if button.payload and button.payload.startswith("history:item:")
    ]
    assert item_payloads, "в истории нет кнопок операций"

    _ctx, views = await click(app, item_payloads[0])
    assert "Операция #" in texts(views)

    tx_id = item_payloads[0].split(":")[-1]
    _ctx, views = await click(app, f"history:delete:{tx_id}")
    assert "Удалить операцию" in texts(views)
    _ctx, views = await click(app, f"history:delete_confirm:{tx_id}")
    assert "удалена" in texts(views)

