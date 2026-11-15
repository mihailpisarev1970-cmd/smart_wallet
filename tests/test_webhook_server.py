"""Тесты webhook-сервера: события MAX и уведомления ЮKassa.

Проверяют маршрутизацию, коды ответов и обработку ошибок без сети и БД.
"""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from bot.utils.ratelimit import RateLimiter
from bot.webhook_server import WebhookApp, build_app

SECRET = "test-secret-123"


class FakeSettings:
    """Минимальные настройки для webhook-сервера."""

    max_updates_mode = "webhook"
    max_webhook_secret = SECRET
    max_webhook_url = ""
    webhook_base_url = "https://example.com"
    ai_subscription_days = 30
    database_url = "postgresql://localhost/test"
    yookassa_shop_id = "1510596"
    yookassa_secret_key = "test_secret"
    yookassa_return_url = "https://example.com/pay/success"

    @property
    def max_webhook_path(self) -> str:
        return f"/webhook/max/{self.max_webhook_secret}"

    @property
    def public_max_webhook_url(self) -> str:
        return self.webhook_base_url.rstrip("/") + self.max_webhook_path


class FakeState(WebhookApp):
    """Настоящий :class:`WebhookApp`, но без БД и MAX-клиента."""

    def __init__(self) -> None:
        self.settings = FakeSettings()
        self.db = object()
        self.api = None
        self.dispatcher = None
        self.yookassa = None
        self.tasks: set[Any] = set()
        self._limiter = RateLimiter()
        self.events: list[dict[str, Any]] = []
        #: Записанные активации подписки (payment_id, amount).
        self.activated: list[tuple[str, str | None]] = []
        #: Результат, который вернёт фейковый SubscriptionService.
        self.activation_result: tuple[bool, str] = (True, "activated")

    def schedule_event(self, update: dict[str, Any]) -> None:
        self.events.append(update)


@pytest.fixture
async def client() -> Any:
    """Тестовый клиент с поднятым приложением."""
    state = FakeState()
    app = build_app(state)
    server = TestServer(app)
    http = TestClient(server)
    await http.start_server()
    http.state_ref = state  # type: ignore[attr-defined]
    try:
        yield http
    finally:
        await http.close()


def webhook_path() -> str:
    return f"/webhook/max/{SECRET}"


# --- События MAX ---------------------------------------------------------


async def test_webhook_accepts_event(client: TestClient) -> None:
    """Событие MAX принимается и ставится в обработку (ответ 200 сразу)."""
    payload = {
        "update_type": "message_created",
        "timestamp": 1794129134772,
        "message": {
            "sender": {"user_id": 72910765, "is_bot": False},
            "recipient": {"chat_id": 461841194, "chat_type": "dialog"},
            "body": {"mid": "mid.test.1", "text": "Потратил 350 на кофе"},
        },
    }
    response = await client.post(webhook_path(), json=payload)

    assert response.status == 200
    assert (await response.json())["ok"] is True
    state = client.state_ref  # type: ignore[attr-defined]
    assert len(state.events) == 1


async def test_webhook_rejects_bad_json(client: TestClient) -> None:
    """Некорректный JSON → 400."""
    response = await client.post(
        webhook_path(), data="не json", headers={"Content-Type": "application/json"}
    )
    assert response.status == 400


@pytest.mark.parametrize("path", ["/webhook/max/wrong-secret", "/webhook/max"])
async def test_webhook_wrong_secret_is_404(client: TestClient, path: str) -> None:
    """Событие на неверный путь (без секрета) не принимается."""
    response = await client.post(path, json={"update_type": "x"})
    assert response.status == 404


async def test_health_endpoint(client: TestClient) -> None:
    """Healthcheck отдаёт 200 и режим работы."""
    response = await client.get("/healthz")
    assert response.status == 200
    body = await response.json()
    assert body["status"] == "ok"
    assert body["mode"] == "webhook"


# --- Оплата ЮKassa -------------------------------------------------------


async def test_pay_pages(client: TestClient) -> None:
    """Страницы возврата ЮKassa отдают 200 и осмысленный текст."""
    success = await client.get("/pay/success")
    assert success.status == 200
    assert "Оплата прошла" in await success.text()

    fail = await client.get("/pay/fail")
    assert fail.status == 200
    assert "Оплата отменена" in await fail.text()


async def test_yookassa_webhook_activates_subscription(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """payment.succeeded → активация подписки по id платежа."""
    activated: list[tuple[str, str | None]] = []

    class FakeService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def activate_by_payment_id(
            self, payment_id: str, amount: str | None = None
        ) -> tuple[bool, str]:
            activated.append((payment_id, amount))
            return True, "activated"

    monkeypatch.setattr("bot.webhook_server.SubscriptionService", FakeService)

    payload = {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {
            "id": "2b8f4a1e-000f-5000-8000-1a2b3c4d5e6f",
            "status": "succeeded",
            "paid": True,
            "amount": {"value": "210.00", "currency": "RUB"},
        },
    }
    response = await client.post("/yookassa/webhook", json=payload)

    assert response.status == 200
    assert activated == [("2b8f4a1e-000f-5000-8000-1a2b3c4d5e6f", "210.00")]


@pytest.mark.parametrize("event", ["payment.canceled", "payment.waiting_for_capture"])
async def test_yookassa_webhook_ignores_other_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, event: str
) -> None:
    """Прочие события не активируют подписку, но и не ломают поток."""
    called: list[str] = []

    class FakeService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def activate_by_payment_id(
            self, payment_id: str, amount: str | None = None
        ) -> tuple[bool, str]:
            called.append(payment_id)
            return True, "activated"

    monkeypatch.setattr("bot.webhook_server.SubscriptionService", FakeService)

    payload = {"type": "notification", "event": event, "object": {"id": "pay-1"}}
    response = await client.post("/yookassa/webhook", json=payload)

    assert response.status == 200
    assert called == [], "подписка не должна активироваться"


async def test_yookassa_webhook_unknown_payment_returns_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Неизвестный платёж → 500, чтобы ЮKassa повторила доставку."""

    class FakeService:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def activate_by_payment_id(
            self, payment_id: str, amount: str | None = None
        ) -> tuple[bool, str]:
            return False, "payment-not-found"

    monkeypatch.setattr("bot.webhook_server.SubscriptionService", FakeService)

    payload = {
        "type": "notification",
        "event": "payment.succeeded",
        "object": {"id": "unknown", "paid": True, "amount": {"value": "210.00"}},
    }
    response = await client.post("/yookassa/webhook", json=payload)
    assert response.status == 500


async def test_yookassa_webhook_bad_json(client: TestClient) -> None:
    """Некорректный JSON → 400."""
    response = await client.post(
        "/yookassa/webhook", data="broken", headers={"Content-Type": "application/json"}
    )
    assert response.status == 400


async def test_robokassa_routes_removed(client: TestClient) -> None:
    """Маршруты Robokassa удалены — переход на ЮKassa завершён."""
    for path in ("/robokassa/result", "/robokassa/success", "/robokassa/fail"):
        response = await client.get(path)
        assert response.status == 404, f"{path} всё ещё существует"

