"""Подписка на AI-функции: создание платежа и активация (ТЗ п. 5.3, 6).

Поток оплаты через ЮKassa (ссылка, без Mini App):

1. ``create_payment`` создаёт платёж в ЮKassa и запись ``pending`` в БД —
   ``external_payment_id`` = ``id`` платежа ЮKassa;
2. пользователь открывает ``confirmation_url`` (внутри MAX);
3. ЮKassa присылает ``payment.succeeded`` на ``/yookassa/webhook``;
4. ``activate_by_payment_id`` активирует подписку (идемпотентно: повторный
   вебхук не продлевает срок второй раз, ТЗ п. 12).
"""

from __future__ import annotations

import logging
from decimal import Decimal

from bot.db import Database
from bot.services.ai_limits import AILimitService
from bot.services.yookassa import (
    YooKassaClient,
    YooKassaError,
    amount_to_str,
    generate_inv_id,
)

logger = logging.getLogger(__name__)


class SubscriptionService:
    """Оформление и активация подписки AI через ЮKassa."""

    def __init__(self, db: Database, client: YooKassaClient, *, days: int = 30) -> None:
        self._db = db
        self._client = client
        self._days = days

    async def create_payment(
        self,
        user_id: int,
        amount: Decimal | int,
        *,
        max_user_id: int | None = None,
        description: str | None = None,
    ) -> tuple[str, str]:
        """Создать платёж. Возвращает ``(url_оплаты, payment_id)``.

        Запись ``pending`` создаётся **до** обращения к ЮKassa: если платёж
        создан, но пользователь не оплатил — запись останется в ``pending``
        и ничего не сломает.
        """
        inv_id = generate_inv_id()
        while await self._db.fetchval(
            "SELECT 1 FROM subscriptions WHERE external_payment_id = $1", str(inv_id)
        ):
            inv_id = generate_inv_id()

        await self._db.execute(
            """
            INSERT INTO subscriptions (user_id, plan, started_at, expires_at, payment_provider,
                                       external_payment_id, amount, status, created_at, updated_at)
            VALUES ($1, 'ai', NULL, NULL, 'yookassa', $2, $3, 'pending', NOW(), NOW())
            """,
            user_id,
            str(inv_id),
            Decimal(amount_to_str(amount)),
        )

        metadata = {"user_id": str(user_id), "inv_id": str(inv_id)}
        if max_user_id:
            metadata["max_user_id"] = str(max_user_id)

        try:
            payment_id, url = await self._client.create_payment(
                amount=amount,
                inv_id=inv_id,
                description=description or "Подписка AI — Умный кошелёк",
                metadata=metadata,
            )
        except YooKassaError:
            # Платёж не создан — убираем «висящую» запись.
            await self._db.execute(
                "DELETE FROM subscriptions WHERE external_payment_id = $1", str(inv_id)
            )
            raise

        # Храним id платежа ЮKassa как основной ключ связи.
        await self._db.execute(
            """
            UPDATE subscriptions
               SET external_payment_id = $2, updated_at = NOW()
             WHERE user_id = $1 AND external_payment_id = $3
            """,
            user_id,
            payment_id,
            str(inv_id),
        )

        logger.info(
            "ЮKassa: платёж создан user=%s payment_id=%s сумма=%s",
            user_id,
            payment_id,
            amount_to_str(amount),
        )
        return url, payment_id

    async def activate_by_payment_id(
        self, payment_id: str, amount: str | None = None
    ) -> tuple[bool, str]:
        """Активировать подписку по подтверждённому платежу ЮKassa.

        Возвращает ``(успех, сообщение)``. Идемпотентно: повторный вебхук
        для уже активированного платежа вернёт успех без продления.
        """
        row = await self._db.fetchrow(
            """
            SELECT id, user_id, amount, status
              FROM subscriptions
             WHERE external_payment_id = $1
            """,
            payment_id,
        )
        if row is None:
            logger.warning("ЮKassa: платёж %s не найден в БД", payment_id)
            return False, "payment-not-found"

        if row["status"] == "active":
            logger.info("ЮKassa: повторное уведомление по %s — уже активно", payment_id)
            return True, "already-active"

        # Сверяем сумму, если она передана: защита от подмены.
        if amount is not None:
            expected = Decimal(amount_to_str(row["amount"]))
            received = Decimal(amount_to_str(amount))
            if expected != received:
                logger.warning(
                    "ЮKassa: сумма не совпадает (ожидали %s, пришло %s) для %s",
                    expected,
                    received,
                    payment_id,
                )
                return False, "amount-mismatch"

        limits = AILimitService(self._db)
        until = await limits.activate_subscription(
            row["user_id"], days=self._days, external_payment_id=payment_id
        )
        logger.info(
            "ЮKassa: подписка активирована user=%s до %s (payment=%s)",
            row["user_id"],
            until,
            payment_id,
        )
        return True, "activated"



async def link_pending_subscriptions(db: Database) -> int:
    """Связать ожидающие платежи (не критично, помощник для админки)."""
    result = await db.execute(
        "UPDATE subscriptions SET updated_at = NOW() WHERE status = 'pending' AND created_at < NOW() - interval '1 day'"
    )
    return int(result.split()[-1]) if result else 0
