"""Месячные бюджеты и лимиты по категориям (ТЗ п. 3.9).

Бюджет — это лимит на месяц (``period`` = ``YYYY-MM``). Общий бюджет хранится
без категории (``category_id IS NULL``), лимит категории — с ``category_id``.

Пороговые уведомления (50/80/100% по умолчанию) отправляются однократно:
отправленные пороги запоминаются в ``budgets.sent_thresholds``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from bot.constants import BUDGET_THRESHOLDS
from bot.db import Database
from bot.utils.dates import period_bounds

logger = logging.getLogger(__name__)

ZERO = Decimal("0.00")


@dataclass(slots=True)
class BudgetRecord:
    """Бюджет вместе с текущим использованием."""

    id: int
    category_id: int | None
    category_name: str | None
    amount: Decimal
    period: str
    spent: Decimal = ZERO
    alert_thresholds: list[int] | None = None
    sent_thresholds: list[int] | None = None

    @property
    def remaining(self) -> Decimal:
        return self.amount - self.spent

    @property
    def percent(self) -> float:
        if not self.amount:
            return 0.0
        return float(self.spent / self.amount * 100)

    @property
    def is_overspent(self) -> bool:
        return self.spent > self.amount

    @property
    def title(self) -> str:
        return self.category_name or "Общий бюджет"

    def thresholds(self) -> list[int]:
        return sorted(self.alert_thresholds or list(BUDGET_THRESHOLDS))


@dataclass(slots=True)
class BudgetAlert:
    """Уведомление о достижении порога."""

    budget_id: int
    title: str
    threshold: int
    percent: float
    spent: Decimal
    amount: Decimal


@dataclass(slots=True)
class BudgetStatus:
    """Сводка по бюджету для экрана."""

    period: str
    overall: BudgetRecord | None
    categories: list[BudgetRecord]
    total_spent: Decimal
    total_limit: Decimal

    @property
    def has_budgets(self) -> bool:
        return bool(self.overall or self.categories)

    @property
    def remaining(self) -> Decimal:
        return self.total_limit - self.total_spent


_SELECT_BUDGET = """
    SELECT b.id, b.category_id, c.name AS category_name, b.amount, b.period,
           b.alert_thresholds, b.sent_thresholds
      FROM budgets b
      LEFT JOIN categories c ON c.id = b.category_id
"""


def _as_int_list(value: object) -> list[int]:
    if isinstance(value, list):
        return [int(item) for item in value if isinstance(item, int | float | str)]
    return []


class BudgetService:
    """Работа с месячными бюджетами."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- запись ----------------------------------------------------------

    async def set_budget(
        self,
        user_id: int,
        period: str,
        amount: Decimal | str | int,
        *,
        category_id: int | None = None,
        alert_thresholds: list[int] | None = None,
    ) -> BudgetRecord:
        """Создать или обновить бюджет (общий или по категории)."""
        from bot.utils.money import to_decimal

        value = to_decimal(amount)
        thresholds = alert_thresholds or list(BUDGET_THRESHOLDS)
        async with self._db.transaction() as conn:
            if category_id is not None:
                owner_type = await conn.fetchval(
                    "SELECT type FROM categories WHERE id = $1 AND user_id = $2",
                    category_id,
                    user_id,
                )
                if owner_type is None:
                    raise ValueError("Категория не найдена.")
                if owner_type != "expense":
                    raise ValueError("Лимит можно ставить только на расходную категорию.")

            # Общий бюджет: уникальность по (user, NULL, period) не ловится
            # ON CONFLICT, поэтому сначала ищем существующую запись.
            existing_id = await conn.fetchval(
                """
                SELECT id FROM budgets
                 WHERE user_id = $1 AND period = $2
                   AND (($3::bigint IS NULL AND category_id IS NULL) OR category_id = $3)
                 LIMIT 1
                """,
                user_id,
                period,
                category_id,
            )
            if existing_id:
                await conn.execute(
                    """
                    UPDATE budgets
                       SET amount = $2, alert_thresholds = $3::jsonb, sent_thresholds = '[]'::jsonb,
                           updated_at = NOW()
                     WHERE id = $1
                    """,
                    existing_id,
                    value,
                    _json(thresholds),
                )
                budget_id = existing_id
            else:
                budget_id = await conn.fetchval(
                    """
                    INSERT INTO budgets (user_id, category_id, amount, period, alert_thresholds,
                                         sent_thresholds, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5::jsonb, '[]'::jsonb, NOW(), NOW())
                    RETURNING id
                    """,
                    user_id,
                    category_id,
                    value,
                    period,
                    _json(thresholds),
                )
            row = await conn.fetchrow(_SELECT_BUDGET + " WHERE b.id = $1", budget_id)

        record = _to_record(row)
        record.spent = await self._spent(
            user_id, period, category_id=record.category_id
        )
        return record

    async def delete(self, budget_id: int, user_id: int) -> bool:
        result = await self._db.execute(
            "DELETE FROM budgets WHERE id = $1 AND user_id = $2", budget_id, user_id
        )
        return result.endswith("1")

    async def mark_thresholds_sent(self, budget_id: int, thresholds: list[int]) -> None:
        await self._db.execute(
            "UPDATE budgets SET sent_thresholds = $2::jsonb, updated_at = NOW() WHERE id = $1",
            budget_id,
            _json(sorted(set(thresholds))),
        )

    # --- чтение ----------------------------------------------------------

    async def _spent(
        self, user_id: int, period: str, *, category_id: int | None = None
    ) -> Decimal:
        start, end = period_bounds(period)
        value = await self._db.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0) FROM transactions
             WHERE user_id = $1 AND type = 'expense'
               AND transaction_date BETWEEN $2 AND $3
               AND ($4::bigint IS NULL OR category_id = $4)
            """,
            user_id,
            start,
            end,
            category_id,
        )
        return value or ZERO

    async def list_for_period(self, user_id: int, period: str) -> list[BudgetRecord]:
        """Все бюджеты пользователя на период с фактическими расходами."""
        rows = await self._db.fetch(
            _SELECT_BUDGET
            + " WHERE b.user_id = $1 AND b.period = $2 ORDER BY b.category_id NULLS FIRST",
            user_id,
            period,
        )
        records = [_to_record(row) for row in rows]
        for record in records:
            record.spent = await self._spent(user_id, period, category_id=record.category_id)
        return records

    async def status(self, user_id: int, period: str) -> BudgetStatus:
        """Сводка по бюджетам: общий, категории, итоги."""
        records = await self.list_for_period(user_id, period)
        overall = next((item for item in records if item.category_id is None), None)
        categories = [item for item in records if item.category_id is not None]
        total_spent = await self._spent(user_id, period)
        total_limit = sum((item.amount for item in records), ZERO)
        return BudgetStatus(
            period=period,
            overall=overall,
            categories=categories,
            total_spent=total_spent,
            total_limit=total_limit,
        )

    async def check_thresholds(
        self, user_id: int, period: str, *, category_id: int | None = None
    ) -> list[BudgetAlert]:
        """Проверить, какие пороги пересечены и ещё не отправлены.

        Возвращает список уведомлений; после показа их нужно отметить через
        :meth:`mark_thresholds_sent`, чтобы не дублировать.
        """
        rows = await self._db.fetch(
            _SELECT_BUDGET
            + """
             WHERE b.user_id = $1 AND b.period = $2
               AND (($3::bigint IS NULL) OR b.category_id IS NULL OR b.category_id = $3)
            """,
            user_id,
            period,
            category_id,
        )
        alerts: list[BudgetAlert] = []
        for row in rows:
            record = _to_record(row)
            record.spent = await self._spent(user_id, period, category_id=record.category_id)
            already = set(_as_int_list(record.sent_thresholds))
            percent = record.percent
            for threshold in record.thresholds():
                if percent >= threshold and threshold not in already:
                    alerts.append(
                        BudgetAlert(
                            budget_id=record.id,
                            title=record.title,
                            threshold=threshold,
                            percent=percent,
                            spent=record.spent,
                            amount=record.amount,
                        )
                    )
        return alerts

    async def mark_alerts_sent(self, alerts: list[BudgetAlert]) -> None:
        """Зафиксировать отправленные уведомления."""
        by_budget: dict[int, list[int]] = {}
        for alert in alerts:
            by_budget.setdefault(alert.budget_id, []).append(alert.threshold)
        for budget_id, thresholds in by_budget.items():
            row = await self._db.fetchrow(
                "SELECT sent_thresholds FROM budgets WHERE id = $1", budget_id
            )
            already = set(_as_int_list(row["sent_thresholds"])) if row else set()
            await self.mark_thresholds_sent(budget_id, sorted(already | set(thresholds)))


def _json(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)


def _to_record(row: object) -> BudgetRecord:
    return BudgetRecord(
        id=row["id"],  # type: ignore[index]
        category_id=row["category_id"],  # type: ignore[index]
        category_name=row["category_name"],  # type: ignore[index]
        amount=row["amount"],  # type: ignore[index]
        period=row["period"],  # type: ignore[index]
        alert_thresholds=_as_int_list(row["alert_thresholds"]),  # type: ignore[index]
        sent_thresholds=_as_int_list(row["sent_thresholds"]),  # type: ignore[index]
    )


