"""Тесты страницы оплаты ``GET /pay/<payment_id>``.

Страница показывает брендированный экран с суммой и кнопкой оплаты
вместо «голой» страницы ЮKassa.
"""

from __future__ import annotations

from bot.payment_page import PaymentInfo, find_payment, resolve_payment_url
from bot.payment_pages import (
    render_cancel_page,
    render_error_page,
    render_not_found_page,
    render_paid_page,
    render_payment_page,
)

# --- рендеринг ------------------------------------------------------------


def test_payment_page_has_amount_and_button() -> None:
    page = render_payment_page(amount_text="210 \u20bd", days=30, payment_url="https://yoomoney.ru/p/123")
    assert "210 \u20bd" in page
    assert "\u041e\u043f\u043b\u0430\u0442\u0438\u0442\u044c 210 \u20bd" in page
    assert "30 дней" in page
    assert "Оплатить" in page
    assert "https://yoomoney.ru/p/123" in page


def test_payment_page_has_fallback_browser_link() -> None:
    """Запасная ссылка нужна, если WebView блокирует 3-D Secure."""
    page = render_payment_page(amount_text="210", days=30, payment_url="https://pay.example/x")
    assert 'target="_blank"' in page
    assert "Открыть в браузере" in page


def test_payment_page_escapes_html() -> None:
    """Сумма и URL экранируются — защита от инъекций."""
    page = render_payment_page(
        amount_text='<script>alert(1)</script>',
        days=30,
        payment_url='https://x/?a="onmouseover="alert(1)',
    )
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


def test_payment_page_warns_about_vpn() -> None:
    """Страница предупреждает: при оплате нужно отключить VPN."""
    page = render_payment_page(amount_text="210", days=30, payment_url="https://x.y/z")
    assert "отключите VPN" in page
    assert "ВАЖНО" in page


def test_payment_page_is_mobile_friendly() -> None:
    page = render_payment_page(amount_text="210", days=30, payment_url="https://x.y/z")
    assert 'name="viewport"' in page
    assert "viewport-fit=cover" in page


def test_status_pages_render() -> None:
    assert "Оплата прошла" in render_paid_page()
    assert "Оплата отменена" in render_cancel_page()
    assert "Счёт не найден" in render_not_found_page()
    assert "Не удалось открыть оплату" in render_error_page()


def test_all_pages_have_brand() -> None:
    for page in (render_paid_page(), render_cancel_page(), render_not_found_page()):
        assert "Умный кошелёк" in page


# --- поиск платежа --------------------------------------------------------


class FakeDb:
    def __init__(self, row: dict | None) -> None:
        self._row = row
        self.queries: list[tuple] = []

    async def fetchrow(self, query: str, *args):
        self.queries.append((query, args))
        return self._row


async def test_find_payment_returns_info() -> None:
    db = FakeDb(
        {
            "external_payment_id": "pay-1",
            "status": "pending",
            "expires_at": None,
            "currency": "RUB",
            "max_user_id": 72910765,
        }
    )
    info = await find_payment(db, "pay-1")
    assert info is not None
    assert info.payment_id == "pay-1"
    assert info.currency == "RUB"
    assert info.max_user_id == 72910765
    assert db.queries[0][1] == ("pay-1",)


async def test_find_payment_missing() -> None:
    info = await find_payment(FakeDb(None), "nope")
    assert info is None


def test_payment_info_paid_flag() -> None:
    assert PaymentInfo("p", "active", "RUB", 1).already_paid is True
    assert PaymentInfo("p", "succeeded", "RUB", 1).already_paid is True
    assert PaymentInfo("p", "canceled", "RUB", 1).already_paid is True
    assert PaymentInfo("p", "pending", "RUB", 1).already_paid is False


# --- ссылка на оплату -----------------------------------------------------


class FakeYK:
    def __init__(self, payload: dict | None = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def get_payment(self, payment_id: str) -> dict:
        if self.error is not None:
            raise self.error
        return self.payload or {}


async def test_resolve_url_for_pending() -> None:
    client = FakeYK(
        {"status": "pending", "confirmation": {"confirmation_url": "https://pay.yk/abc"}}
    )
    assert await resolve_payment_url(client, "abc") == "https://pay.yk/abc"


async def test_resolve_url_none_when_succeeded() -> None:
    """Для успешного платежа ссылка не нужна."""
    client = FakeYK({"status": "succeeded", "confirmation": {"confirmation_url": "https://x"}})
    assert await resolve_payment_url(client, "abc") is None


async def test_resolve_url_none_on_error() -> None:
    client = FakeYK(error=RuntimeError("сеть"))
    assert await resolve_payment_url(client, "abc") is None


async def test_resolve_url_none_without_confirmation() -> None:
    client = FakeYK({"status": "pending"})
    assert await resolve_payment_url(client, "abc") is None
