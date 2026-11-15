"""Лимиты AI и подписка (ТЗ п. 5.3, 12).

Правила:

* У пользователя есть ``AI_FREE_REQUESTS`` (по умолчанию 10) бесплатных
  AI-запросов **навсегда**.
* Счётчик ``ai_requests_used`` увеличивается **один раз за цикл**
  (STT + LLM), а не дважды.
* При активной подписке лимит не применяется.
* Если STT/LLM недоступны — запрос не списывается.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from bot.db import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AILimitStatus:
    """Состояние лимита AI для пользователя."""

    used: int
    free_limit: int
    subscription_active: bool
    subscription_until: datetime | None

    @property
    def remaining(self) -> int:
        if self.subscription_active:
            return -1  # неограниченно
        return max(0, self.free_limit - self.used)

    @property
    def allowed(self) -> bool:
        return self.subscription_active or self.used < self.free_limit


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AILimitService:
    """Проверка и списание AI-запросов."""

    def __init__(self, db: Database, free_requests: int = 10) -> None:
        self._db = db
        self._free_requests = max(0, free_requests)

    async def status(self, user_id: int) -> AILimitStatus:
        row = await self._db.fetchrow(
            """
            SELECT ai_requests_used, ai_subscription_status, ai_subscription_until
              FROM users WHERE id = $1
            """,
            user_id,
        )
        if not row:
            return AILimitStatus(0, self._free_requests, False, None)

        until = row["ai_subscription_until"]
        active = (
            row["ai_subscription_status"] == "paid"
            and until is not None
            and until > _utcnow()
        )
        return AILimitStatus(
            used=int(row["ai_requests_used"] or 0),
            free_limit=self._free_requests,
            subscription_active=bool(active),
            subscription_until=until,
        )

    async def can_use(self, user_id: int) -> tuple[bool, AILimitStatus]:
        status = await self.status(user_id)
        return status.allowed, status

    async def consume(self, user_id: int) -> AILimitStatus:
        """Списать один AI-запрос (вызывается один раз за цикл STT+LLM)."""
        await self._db.execute(
            "UPDATE users SET ai_requests_used = ai_requests_used + 1, updated_at = NOW() "
            "WHERE id = $1",
            user_id,
        )
        return await self.status(user_id)

    # --- подписка --------------------------------------------------------

    async def activate_subscription(
        self, user_id: int, *, days: int = 30, external_payment_id: str | None = None
    ) -> datetime:
        """Активировать/продлить подписку AI на ``days`` дней."""
        row = await self._db.fetchrow(
            "SELECT ai_subscription_until FROM users WHERE id = $1", user_id
        )
        now = _utcnow()
        current_until = row["ai_subscription_until"] if row else None
        base = current_until if current_until and current_until > now else now
        new_until = base + timedelta(days=days)
        await self._db.execute(
            """
            UPDATE users
               SET ai_subscription_status = 'paid', ai_subscription_until = $2, updated_at = NOW()
             WHERE id = $1
            """,
            user_id,
            new_until,
        )
        await self._db.execute(
            """
            UPDATE subscriptions
               SET status = 'active', started_at = COALESCE(started_at, NOW()),
                   expires_at = $3, updated_at = NOW()
             WHERE user_id = $1 AND ($2::text IS NULL OR external_payment_id = $2)
            """,
            user_id,
            external_payment_id,
            new_until,
        )
        logger.info("Подписка AI активирована для user=%s до %s", user_id, new_until)
        return new_until

    async def deactivate_subscription(self, user_id: int) -> None:
        await self._db.execute(
            """
            UPDATE users
               SET ai_subscription_status = 'expired', updated_at = NOW()
             WHERE id = $1
            """,
            user_id,
        )

    async def expire_outdated(self) -> int:
        """Пометить истёкшие подписки (можно вызывать из планировщика)."""
        result = await self._db.execute(
            """
            UPDATE users
               SET ai_subscription_status = 'expired', updated_at = NOW()
             WHERE ai_subscription_status = 'paid'
               AND ai_subscription_until IS NOT NULL
               AND ai_subscription_until <= NOW()
            """
        )
        expired = int(result.split()[-1]) if result else 0
        if expired:
            logger.info("Истекло подписок: %s", expired)
        return expired
