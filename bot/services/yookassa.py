"""ЮKassa: создание платежа и проверка статуса (ТЗ п. 5.3, 6).

Почему ЮKassa, а не Robokassa: магазин Robokassa отклонял все платежи с
кодом 29 («Оплата счетов недоступна») независимо от параметров и подписи.
ЮKassa приняла те же реквизиты сразу (``GET /v3/me`` → ``status: enabled``).

Поток оплаты (без Mini App, по ссылке):

1. ``create_payment`` создаёт платёж в ЮKassa **и** запись ``pending`` в БД;
2. пользователь открывает ``confirmation_url`` (внутри MAX, в webview);
3. после оплаты ЮKassa шлёт ``payment.succeeded`` на ``/yookassa/webhook``;
4. ``activate_by_payment_id`` активирует подписку на 30 дней (идемпотентно).

API: https://yookassa.ru/developers/api — Basic Auth ``shopId:secretKey``,
обязательный ``Idempotence-Key`` для POST.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from bot.config import Settings

logger = logging.getLogger(__name__)

#: Базовый адрес API ЮKassa.
API_BASE_URL = "https://api.yookassa.ru/v3"

#: Таймаут запросов к ЮKassa.
API_TIMEOUT_SECONDS = 30.0

#: Описание платежа по умолчанию.
DEFAULT_DESCRIPTION = "Подписка AI — Умный кошелёк"

#: Сколько раз повторять запрос при сетевой ошибке (таймаут/обрыв).
#: Реальный случай: `ConnectTimeout` при создании платежа — сеть «отпустило»
#: через минуту, и без повтора пользователь получил ошибку.
MAX_NETWORK_RETRIES = 3

#: Пауза перед повтором, сек (умножается на номер попытки).
RETRY_DELAY_SECONDS = 1.5


def generate_inv_id() -> int:
    """Сгенерировать числовой номер заказа (уникальный в пределах магазина)."""
    return secrets.randbelow(2_000_000_000) + 1


def amount_to_str(amount: Decimal | int | float | str) -> str:
    """Сумма в формате ЮKassa: всегда два знака после запятой."""
    return f"{Decimal(str(amount)).quantize(Decimal('0.01')):.2f}"


@dataclass(slots=True)
class YooKassaConfig:
    """Реквизиты магазина ЮKassa."""

    shop_id: str
    secret_key: str
    return_url: str = ""

    @classmethod
    def from_settings(cls, settings: Settings) -> YooKassaConfig:
        return cls(
            shop_id=getattr(settings, "yookassa_shop_id", ""),
            secret_key=getattr(settings, "yookassa_secret_key", ""),
            return_url=getattr(settings, "yookassa_return_url", ""),
        )

    @property
    def configured(self) -> bool:
        """Заданы ли оба реквизита."""
        return bool(self.shop_id and self.secret_key)


class YooKassaError(Exception):
    """Ошибка API ЮKassa."""


class YooKassaClient:
    """Минимальный клиент ЮKassa: создать платёж, узнать статус."""

    def __init__(
        self,
        config: YooKassaConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = API_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._transport = transport
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        from bot.utils.tls import verify_option

        return httpx.AsyncClient(
            base_url=API_BASE_URL,
            auth=(self._config.shop_id, self._config.secret_key),
            timeout=httpx.Timeout(self._timeout, connect=15.0),
            verify=verify_option(),
            transport=self._transport,
        )

    async def _request_with_retry(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        """Выполнить запрос с повтором при сетевых ошибках.

        Сеть до ``api.yookassa.ru`` иногда «моргает» (``ConnectTimeout``,
        обрыв TLS). Без повтора пользователь видит «не удалось создать
        платёж», хотя через секунду всё работает.
        """
        last_error: Exception | None = None
        for attempt in range(1, MAX_NETWORK_RETRIES + 1):
            try:
                async with self._client() as client:
                    return await client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < MAX_NETWORK_RETRIES:
                    logger.warning(
                        "ЮKassa: сетевая ошибка %s (%s /%s), попытка %s/%s",
                        exc.__class__.__name__,
                        method,
                        path,
                        attempt,
                        MAX_NETWORK_RETRIES,
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS * attempt)

        raise YooKassaError(
            f"ЮKassa: сетевая ошибка ({(last_error or Exception()).__class__.__name__})"
        ) from last_error

    async def create_payment(
        self,
        *,
        amount: Decimal | int | str,
        inv_id: str | int,
        description: str = DEFAULT_DESCRIPTION,
        return_url: str | None = None,
        metadata: dict[str, Any] | None = None,
        capture: bool = True,
    ) -> tuple[str, str]:
        """Создать платёж. Возвращает ``(payment_id, confirmation_url)``.

        ``capture=True`` — деньги списываются сразу (подписка на месяц).
        """
        if not self._config.configured:
            raise YooKassaError(
                "ЮKassa не настроена: задайте YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY"
            )

        payload: dict[str, Any] = {
            "amount": {"value": amount_to_str(amount), "currency": "RUB"},
            "capture": capture,
            "description": description[:128],
            "metadata": {"inv_id": str(inv_id), **(metadata or {})},
        }
        redirect = return_url or self._config.return_url
        if redirect:
            payload["confirmation"] = {"type": "redirect", "return_url": redirect}

        headers = {"Idempotence-Key": str(uuid.uuid4())}
        response = await self._request_with_retry("POST", "/payments", json=payload, headers=headers)

        if response.status_code >= 400:
            raise YooKassaError(f"ЮKassa: HTTP {response.status_code} — {response.text[:300]}")

        data = response.json()
        payment_id = str(data.get("id") or "")
        confirmation = data.get("confirmation") or {}
        url = str(confirmation.get("confirmation_url") or "")
        if not payment_id or not url:
            raise YooKassaError(f"ЮKassa: неожиданный ответ — {str(data)[:300]}")

        logger.info(
            "ЮKassa: платёж создан id=%s сумма=%s status=%s",
            payment_id,
            payload["amount"]["value"],
            data.get("status"),
        )
        return payment_id, url

    async def get_payment(self, payment_id: str) -> dict[str, Any]:
        """Получить платёж по id (для проверки статуса)."""
        response = await self._request_with_retry("GET", f"/payments/{payment_id}")

        if response.status_code >= 400:
            raise YooKassaError(f"ЮKassa: HTTP {response.status_code} — {response.text[:300]}")
        return response.json()

    async def get_me(self) -> dict[str, Any]:
        """Информация о магазине (проверка ключей)."""
        response = await self._request_with_retry("GET", "/me")

        if response.status_code >= 400:
            raise YooKassaError(f"ЮKassa: HTTP {response.status_code} — {response.text[:300]}")
        return response.json()


def build_client(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> YooKassaClient:
    """Собрать клиент ЮKassa по настройкам."""
    return YooKassaClient(YooKassaConfig.from_settings(settings), transport=transport)

