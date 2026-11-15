"""Цели накопления (ТЗ п. 3.10).

Цель — название, целевая сумма и (опционально) срок. Пользователь вносит
суммы вручную («Отложить»), прогресс считается программно.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bot.db import Database
from bot.utils.money import to_decimal

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


@dataclass(slots=True)
class GoalRecord:
    """Цель накопления с рассчитанным прогрессом."""

    id: int
    user_id: int
    name: str
    target_amount: Decimal
    saved_amount: Decimal
    deadline: date | None
    is_completed: bool

    @property
    def remaining(self) -> Decimal:
        return max(ZERO, self.target_amount - self.saved_amount)

    @property
    def percent(self) -> float:
        if not self.target_amount:
            return 0.0
        return float(min(Decimal(100), self.saved_amount / self.target_amount * 100))

    @property
    def days_left(self) -> int | None:
        if not self.deadline:
            return None
        return (self.deadline - date.today()).days

    @classmethod
    def from_record(cls, row: object) -> GoalRecord:
        return cls(
            id=row["id"],  # type: ignore[index]
            user_id=row["user_id"],  # type: ignore[index]
            name=row["name"],  # type: ignore[index]
            target_amount=row["target_amount"],  # type: ignore[index]
            saved_amount=row["saved_amount"],  # type: ignore[index]
            deadline=row["deadline"],  # type: ignore[index]
            is_completed=row["is_completed"],  # type: ignore[index]
        )


class GoalService:
    """Создание, пополнение и удаление целей."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        user_id: int,
        name: str,
        target_amount: Decimal | str | int,
        *,
        deadline: date | None = None,
        saved_amount: Decimal | str | int = ZERO,
    ) -> GoalRecord:
        target = to_decimal(target_amount)
        saved = to_decimal(saved_amount)
        row = await self._db.fetchrow(
            """
            INSERT INTO goals (user_id, name, target_amount, saved_amount, deadline,
                               is_completed, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, FALSE, NOW(), NOW())
            RETURNING id, user_id, name, target_amount, saved_amount, deadline, is_completed
            """,
            user_id,
            name.strip()[:128],
            target,
            saved,
            deadline,
        )
        logger.info("Цель «%s» создана: %s / %s", name, saved, target)
        return GoalRecord.from_record(row)

    async def list(self, user_id: int, *, include_completed: bool = False) -> list[GoalRecord]:
        rows = await self._db.fetch(
            """
            SELECT id, user_id, name, target_amount, saved_amount, deadline, is_completed
              FROM goals
             WHERE user_id = $1 AND ($2::bool OR is_completed = FALSE)
             ORDER BY is_completed, deadline NULLS LAST, created_at
            """,
            user_id,
            include_completed,
        )
        return [GoalRecord.from_record(row) for row in rows]

    async def get(self, goal_id: int, user_id: int) -> GoalRecord | None:
        row = await self._db.fetchrow(
            """
            SELECT id, user_id, name, target_amount, saved_amount, deadline, is_completed
              FROM goals WHERE id = $1 AND user_id = $2
            """,
            goal_id,
            user_id,
        )
        return GoalRecord.from_record(row) if row else None

    async def contribute(self, goal_id: int, user_id: int, amount: Decimal | str | int) -> GoalRecord | None:
        """Отложить сумму в цель. При достижении цели ставится флаг «выполнена»."""
        value = to_decimal(amount)
        if value <= 0:
            raise ValueError("Сумма должна быть больше нуля.")
        row = await self._db.fetchrow(
            """
            UPDATE goals
               SET saved_amount = saved_amount + $3,
                   is_completed = (saved_amount + $3) >= target_amount,
                   completed_at = CASE WHEN (saved_amount + $3) >= target_amount
                                       THEN COALESCE(completed_at, NOW()) ELSE completed_at END,
                   updated_at = NOW()
             WHERE id = $1 AND user_id = $2
             RETURNING id, user_id, name, target_amount, saved_amount, deadline, is_completed
            """,
            goal_id,
            user_id,
            value,
        )
        return GoalRecord.from_record(row) if row else None

    async def delete(self, goal_id: int, user_id: int) -> bool:
        result = await self._db.execute(
            "DELETE FROM goals WHERE id = $1 AND user_id = $2", goal_id, user_id
        )
        return result.endswith("1")
