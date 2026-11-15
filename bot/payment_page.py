"""Логика страницы оплаты: ``GET /pay/<payment_id>``.

Страница открывается по ссылке из бота и показывает сумму + кнопку оплаты.
Если ``confirmation_url`` от ЮKassa ещё жив — ведём прямо на него; если
истёк, запрашиваем платёж заново через API и берём актуальный URL.

Зачем своя страница вместо прямой ссылки ЮKassa:

* брендинг проекта (логотип, сумма, что входит в подписку);
* единая точка для будущего мини-приложения MAX (``open_app``);
* запасная кнопка «Открыть в браузере» на случай блокировки 3-D Secure
  в WebView.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: Достать платёж из подписки (external_payment_id = id платежа ЮKassa).
PAYMENT_QUERY = """
SELECT s.external_payment_id,
       s.status,
       s.expires_at,
       u.currency,
       u.max_user_id
  FROM subscriptions s
  JOIN users u ON u.id = s.user_id
 WHERE s.external_payment_id = $1
 LIMIT 1
"""

#: Статусы, при которых оплата уже не нужна.
PAID_STATUSES = frozenset({"active", "succeeded", "paid", "canceled", "cancelled"})


@dataclass(slots=True)
class PaymentInfo:
    """Данные платежа для страницы."""

    payment_id: str
    status: str
    currency: str
    max_user_id: int | None

    @property
    def already_paid(self) -> bool:
        return self.status in PAID_STATUSES


async def find_payment(db: Any, payment_id: str) -> PaymentInfo | None:
    """Найти платёж в БД. ``None`` — счёт не найден."""
    row = await db.fetchrow(PAYMENT_QUERY, payment_id)
    if not row:
        return None
    return PaymentInfo(
        payment_id=row["external_payment_id"],
        status=str(row["status"] or ""),
        currency=str(row["currency"] or "RUB"),
        max_user_id=row["max_user_id"],
    )


async def resolve_payment_url(client: Any, payment_id: str) -> str | None:
    """Получить актуальную ссылку на оплату у ЮKassa.

    ``confirmation_url`` живёт ограниченное время, поэтому запрашиваем
    платёж заново. Для завершённых/отменённых платежей ссылки нет.
    """
    try:
        payload = await client.get_payment(payment_id)
    except Exception as exc:  # сеть, 404, 401 — просто покажем ошибку
        logger.warning("Не удалось получить платёж %s: %s", payment_id, exc)
        return None

    if not isinstance(payload, dict):
        return None
    status = str(payload.get("status") or "")
    confirmation = payload.get("confirmation") or {}
    url = confirmation.get("confirmation_url") if isinstance(confirmation, dict) else None
    if status not in {"pending", "waiting_for_capture"}:
        logger.info("Платёж %s в статусе %s — ссылка не нужна", payment_id, status)
        return None
    return str(url) if url else None
