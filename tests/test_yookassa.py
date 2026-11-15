"""Тесты клиента ЮKassa и вебхук-сервера оплаты.

Проверяют создание платежа, коды ответов и обработку уведомлений
без обращения к реальному API (httpx.MockTransport).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest

from bot.services.yookassa import (
    YooKassaClient,
    YooKassaConfig,
    YooKassaError,
    amount_to_str,
    build_client,
)

SECRET = "test-secret-123"
SHOP_ID = "1510596"
SECRET_KEY = "test_secret_key"


def make_config(**overrides: Any) -> YooKassaConfig:
    """Конфигурация ЮKassa для тестов."""
    base = {
        "shop_id": SHOP_ID,
        "secret_key": SECRET_KEY,
        "return_url": "https://example.com/pay/success",
    }
    base.update(overrides)
    return YooKassaConfig(**base)


def make_client(handler, config: YooKassaConfig | None = None) -> YooKassaClient:
    """Клиент с подменённым транспортом."""
    return YooKassaClient(config or make_config(), transport=httpx.MockTransport(handler))


# --- Сумма ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (210, "210.00"),
        ("210", "210.00"),
        ("210.5", "210.50"),
        (Decimal("210.00"), "210.00"),
        (Decimal("99.99"), "99.99"),
        (Decimal("0.1"), "0.10"),
    ],
)
def test_amount_to_str(value: Any, expected: str) -> None:
    """Сумма всегда в формате ЮKassa — два знака после запятой."""
    assert amount_to_str(value) == expected


def test_config_configured() -> None:
    assert make_config().configured
    assert not make_config(shop_id="").configured
    assert not make_config(secret_key="").configured


# --- Создание платежа ----------------------------------------------------


async def test_create_payment_success() -> None:
    """Платёж создаётся: возвращаются id и ссылка на оплату."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "id": "2b8f4a1e-000f-5000-8000-1a2b3c4d5e6f",
                "status": "pending",
                "paid": False,
                "amount": {"value": "210.00", "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "confirmation_url": "https://yoomoney.ru/checkout/payments/v2/contract?orderId=abc",
                },
            },
        )

    client = make_client(handler)
    payment_id, url = await client.create_payment(amount=Decimal("210"), inv_id=12345)

    assert payment_id == "2b8f4a1e-000f-5000-8000-1a2b3c4d5e6f"
    assert url.startswith("https://yoomoney.ru/checkout/")
    assert captured["url"].endswith("/payments")
    # Обязательный заголовок ЮKassa
    assert "idempotence-key" in {key.lower() for key in captured["headers"]}
    # Сумма и описание в теле
    assert "210.00" in captured["body"]
    assert "RUB" in captured["body"]


async def test_create_payment_uses_basic_auth() -> None:
    """Авторизация — Basic Auth shopId:secretKey."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization", "")
        return httpx.Response(
            200,
            json={
                "id": "pay-1",
                "status": "pending",
                "confirmation": {"confirmation_url": "https://yoomoney.ru/x"},
            },
        )

    client = make_client(handler)
    await client.create_payment(amount=210, inv_id=1)

    assert captured["auth"].startswith("Basic ")
    # base64(1510596:test_secret_key)
    import base64

    decoded = base64.b64decode(captured["auth"].split(" ", 1)[1]).decode()
    assert decoded == f"{SHOP_ID}:{SECRET_KEY}"


async def test_create_payment_sends_metadata() -> None:
    """В metadata передаются user_id и inv_id — по ним находим платёж."""
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"id": "p1", "confirmation": {"confirmation_url": "https://x"}},
        )

    client = make_client(handler)
    await client.create_payment(
        amount=210, inv_id=777, metadata={"user_id": "42", "max_user_id": "72910765"}
    )

    assert "user_id" in captured["body"]
    assert "42" in captured["body"]
    assert "777" in captured["body"]


async def test_create_payment_requires_config() -> None:
    """Без ключей — понятная ошибка, без запроса к API."""
    client = make_client(lambda request: httpx.Response(200), make_config(shop_id=""))
    with pytest.raises(YooKassaError, match="не настроена"):
        await client.create_payment(amount=210, inv_id=1)


async def test_create_payment_api_error() -> None:
    """Ошибка API превращается в YooKassaError с текстом ответа."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"type": "error", "description": "Bad amount"})

    client = make_client(handler)
    with pytest.raises(YooKassaError, match="400"):
        await client.create_payment(amount=210, inv_id=1)


async def test_create_payment_malformed_response() -> None:
    """Ответ без confirmation_url — ошибка, а не «пустая» ссылка."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "p1", "status": "pending"})

    client = make_client(handler)
    with pytest.raises(YooKassaError, match="неожиданный ответ"):
        await client.create_payment(amount=210, inv_id=1)


async def test_get_payment() -> None:
    """Статус платежа запрашивается по id."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/payments/pay-xyz")
        return httpx.Response(200, json={"id": "pay-xyz", "status": "succeeded", "paid": True})

    client = make_client(handler)
    data = await client.get_payment("pay-xyz")
    assert data["status"] == "succeeded"
    assert data["paid"] is True


async def test_get_me() -> None:
    """Проверка ключей: /me отдаёт статус магазина."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/me")
        return httpx.Response(200, json={"account_id": SHOP_ID, "status": "enabled"})

    client = make_client(handler)
    data = await client.get_me()
    assert data["status"] == "enabled"


def test_build_client_from_settings() -> None:
    """build_client собирает клиент из настроек."""

    class Settings:
        yookassa_shop_id = SHOP_ID
        yookassa_secret_key = SECRET_KEY
        yookassa_return_url = "https://example.com/return"

    client = build_client(Settings())
    assert isinstance(client, YooKassaClient)


# --- Повтор при сетевых ошибках ------------------------------------------


async def test_create_payment_retries_on_network_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """РЕГРЕССИЯ: ConnectTimeout не должен ломать оплату.

    Реальный случай: сеть до api.yookassa.ru «моргнула», бот показал
    «не удалось создать платёж», хотя повтор через секунду сработал бы.
    """
    import bot.services.yookassa as yk

    monkeypatch.setattr(yk, "RETRY_DELAY_SECONDS", 0)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] < 3:
            raise httpx.ConnectTimeout("timeout", request=request)
        return httpx.Response(
            200,
            json={
                "id": "pay-retry",
                "confirmation": {"confirmation_url": "https://yoomoney.ru/x"},
            },
        )

    client = make_client(handler)
    payment_id, url = await client.create_payment(amount=210, inv_id=1)

    assert payment_id == "pay-retry"
    assert url.startswith("https://")
    assert calls["count"] == 3, "должно быть две неудачные попытки и одна успешная"


async def test_create_payment_gives_up_after_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если сеть недоступна совсем — понятная ошибка после всех попыток."""
    import bot.services.yookassa as yk

    monkeypatch.setattr(yk, "RETRY_DELAY_SECONDS", 0)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectTimeout("timeout", request=request)

    client = make_client(handler)
    with pytest.raises(YooKassaError, match="сетевая ошибка"):
        await client.create_payment(amount=210, inv_id=1)

    assert calls["count"] == yk.MAX_NETWORK_RETRIES


async def test_get_me_also_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повтор работает и для GET-запросов."""
    import bot.services.yookassa as yk

    monkeypatch.setattr(yk, "RETRY_DELAY_SECONDS", 0)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={"account_id": SHOP_ID, "status": "enabled"})

    client = make_client(handler)
    data = await client.get_me()

    assert data["status"] == "enabled"
    assert calls["count"] == 2
