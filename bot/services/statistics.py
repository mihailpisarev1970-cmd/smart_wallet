"""Баланс и статистика — полностью программный расчёт (ТЗ п. 3.6, 3.8).

Баланс не хранится в БД как источник истины: он всегда вычисляется как
``Доходы − Расходы`` по операциям пользователя.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from bot.db import Database
from bot.utils.dates import DateRange, period_bounds

ZERO = Decimal("0.00")


@dataclass(slots=True)
class Totals:
    """Суммы доходов и расходов за период."""

    income: Decimal = ZERO
    expense: Decimal = ZERO

    @property
    def balance(self) -> Decimal:
        return self.income - self.expense

    def __add__(self, other: Totals) -> Totals:
        return Totals(income=self.income + other.income, expense=self.expense + other.expense)


@dataclass(slots=True)
class CategoryTotal:
    """Итог по категории."""

    category_id: int | None
    name: str
    total: Decimal
    share: float = 0.0
    count: int = 0


@dataclass(slots=True)
class MonthPoint:
    """Точка динамики по месяцам."""

    period: str
    income: Decimal
    expense: Decimal

    @property
    def diff(self) -> Decimal:
        return self.income - self.expense


@dataclass(slots=True)
class Statistics:
    """Итоговая статистика для экрана."""

    range_label: str
    totals: Totals
    by_category: list[CategoryTotal] = field(default_factory=list)
    top_category: CategoryTotal | None = None
    monthly: list[MonthPoint] = field(default_factory=list)
    current_month: Totals = field(default_factory=Totals)
    previous_month: Totals = field(default_factory=Totals)
    days_left_in_month: int = 0
    avg_per_day: Decimal = ZERO
    period_start: date | None = None
    period_end: date | None = None


class StatisticsService:
    """Расчёт баланса и статистики."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- базовые суммы ---------------------------------------------------

    async def totals(self, user_id: int, date_range: DateRange) -> Totals:
        """Доходы/расходы за произвольный период."""
        row = await self._db.fetchrow(
            """
            SELECT
              COALESCE(SUM(amount) FILTER (WHERE type = 'income'), 0) AS income,
              COALESCE(SUM(amount) FILTER (WHERE type = 'expense'), 0) AS expense
              FROM transactions
             WHERE user_id = $1 AND transaction_date BETWEEN $2 AND $3
            """,
            user_id,
            date_range.start,
            date_range.end,
        )
        if not row:
            return Totals()
        return Totals(income=row["income"] or ZERO, expense=row["expense"] or ZERO)

    async def lifetime_totals(self, user_id: int) -> Totals:
        """Суммы за всё время — для «общего баланса»."""
        row = await self._db.fetchrow(
            """
            SELECT
              COALESCE(SUM(amount) FILTER (WHERE type = 'income'), 0) AS income,
              COALESCE(SUM(amount) FILTER (WHERE type = 'expense'), 0) AS expense
              FROM transactions WHERE user_id = $1
            """,
            user_id,
        )
        if not row:
            return Totals()
        return Totals(income=row["income"] or ZERO, expense=row["expense"] or ZERO)

    async def totals_by_period(self, user_id: int, period: str) -> Totals:
        start, end = period_bounds(period)
        return await self.totals(user_id, DateRange(start, end, period))

    # --- категории -------------------------------------------------------

    async def _category_totals(
        self, user_id: int, type_: str, date_range: DateRange
    ) -> list[CategoryTotal]:
        rows = await self._db.fetch(
            """
            SELECT t.category_id,
                   COALESCE(c.name, 'Без категории') AS name,
                   SUM(t.amount) AS total,
                   COUNT(*) AS count
              FROM transactions t
              LEFT JOIN categories c ON c.id = t.category_id
             WHERE t.user_id = $1 AND t.type = $2
               AND t.transaction_date BETWEEN $3 AND $4
             GROUP BY t.category_id, c.name
             ORDER BY total DESC
            """,
            user_id,
            type_,
            date_range.start,
            date_range.end,
        )
        items = [
            CategoryTotal(
                category_id=row["category_id"],
                name=row["name"],
                total=row["total"] or ZERO,
                count=int(row["count"] or 0),
            )
            for row in rows
        ]
        grand_total = sum((item.total for item in items), ZERO)
        for item in items:
            item.share = float(item.total / grand_total * 100) if grand_total else 0.0
        return items

    async def expense_by_category(
        self, user_id: int, date_range: DateRange
    ) -> list[CategoryTotal]:
        """Расходы по категориям, по убыванию суммы."""
        return await self._category_totals(user_id, "expense", date_range)

    async def income_by_category(self, user_id: int, date_range: DateRange) -> list[CategoryTotal]:
        return await self._category_totals(user_id, "income", date_range)

    async def category_expense_total(
        self, user_id: int, category_id: int, date_range: DateRange
    ) -> Decimal:
        value = await self._db.fetchval(
            """
            SELECT COALESCE(SUM(amount), 0) FROM transactions
             WHERE user_id = $1 AND type = 'expense' AND category_id = $2
               AND transaction_date BETWEEN $3 AND $4
            """,
            user_id,
            category_id,
            date_range.start,
            date_range.end,
        )
        return value or ZERO

    async def balance_totals(self, user_id: int, date_range: DateRange) -> Totals:
        """Совместимый алиас для экрана баланса."""
        return await self.totals(user_id, date_range)

    # --- динамика по месяцам ---------------------------------------------

    async def monthly_dynamics(self, user_id: int, months: int = 6) -> list[MonthPoint]:
        """Динамика по последним ``months`` месяцам, включая текущий."""
        rows = await self._db.fetch(
            """
            SELECT to_char(transaction_date, 'YYYY-MM') AS period,
                   COALESCE(SUM(amount) FILTER (WHERE type = 'income'), 0) AS income,
                   COALESCE(SUM(amount) FILTER (WHERE type = 'expense'), 0) AS expense
              FROM transactions
             WHERE user_id = $1
               AND transaction_date >= date_trunc('month', CURRENT_DATE)
                                        - make_interval(months => $2::int - 1)
             GROUP BY 1
             ORDER BY 1
            """,
            user_id,
            max(1, months),
        )
        data = {
            row["period"]: MonthPoint(
                period=row["period"], income=row["income"] or ZERO, expense=row["expense"] or ZERO
            )
            for row in rows
        }

        # Заполняем «пустые» месяцы, чтобы график был непрерывным.
        from bot.utils.dates import current_period, previous_period

        current = current_period()
        periods: list[str] = [current]
        for _ in range(max(1, months) - 1):
            current = previous_period(current)
            periods.append(current)

        return [data.get(key, MonthPoint(period=key, income=ZERO, expense=ZERO))
                for key in reversed(periods)]

    # --- сводная статистика ----------------------------------------------

    async def build(
        self,
        user_id: int,
        date_range: DateRange,
        *,
        tz_name: str | None = None,
        months: int = 6,
    ) -> Statistics:
        """Полная статистика по периоду для отображения (ТЗ п. 3.8)."""
        from datetime import timedelta

        from bot.utils.dates import current_period, previous_period, today_in_tz

        today = today_in_tz(tz_name)
        totals = await self.totals(user_id, date_range)
        by_category = await self.expense_by_category(user_id, date_range)
        period = current_period(tz_name)
        current = await self.totals_by_period(user_id, period)
        prev = await self.totals_by_period(user_id, previous_period(period))

        # Последний день текущего месяца и сколько дней осталось.
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        month_end = next_month - timedelta(days=1)
        days_left = max(0, (month_end - today).days)

        days_in_period = max(1, (date_range.end - date_range.start).days + 1)
        avg = (totals.expense / days_in_period).quantize(Decimal("0.01"))

        return Statistics(
            range_label=date_range.label,
            totals=totals,
            by_category=by_category,
            top_category=by_category[0] if by_category else None,
            monthly=await self.monthly_dynamics(user_id, months),
            current_month=current,
            previous_month=prev,
            days_left_in_month=days_left,
            avg_per_day=avg,
            period_start=date_range.start,
            period_end=date_range.end,
        )


