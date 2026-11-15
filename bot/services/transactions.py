"""Бизнес-логика операций: доходы и расходы (ТЗ п. 3.3, 3.4, 3.7).

Все финансовые изменения выполняются внутри транзакции БД, суммы — только
``Decimal`` (``NUMERIC(14,2)``). Каждая операция проверяется на принадлежность
пользователю — чужие записи недоступны.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from bot.constants import EXPENSE, INCOME, SOURCE_BUTTON, TRANSACTION_TYPE_LABELS
from bot.db import Database
from bot.utils.dates import DateRange, today_in_tz
from bot.utils.money import MAX_AMOUNT, to_decimal

logger = logging.getLogger(__name__)

_SELECT_TX = """
    SELECT t.id, t.user_id, t.type, t.amount, t.currency, t.category_id,
           c.name AS category_name, t.transaction_date, t.comment, t.source,
           t.created_at
      FROM transactions t
      LEFT JOIN categories c ON c.id = t.category_id
"""


class TransactionError(Exception):
    """Ошибка валидации операции (показывается пользователю)."""


@dataclass(slots=True)
class TransactionRecord:
    """Операция в удобном для отображения виде."""

    id: int
    user_id: int
    type: str
    amount: Decimal
    currency: str
    category_id: int | None
    category_name: str
    transaction_date: date
    comment: str
    source: str
    created_at: Any

    @property
    def is_expense(self) -> bool:
        return self.type == EXPENSE

    @property
    def sign_symbol(self) -> str:
        return "−" if self.is_expense else "+"

    @property
    def type_label(self) -> str:
        return TRANSACTION_TYPE_LABELS.get(self.type, self.type)

    @classmethod
    def from_record(cls, row: Any) -> TransactionRecord:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            type=row["type"],
            amount=row["amount"],
            currency=row["currency"],
            category_id=row["category_id"],
            category_name=row["category_name"] or "Без категории",
            transaction_date=row["transaction_date"],
            comment=row["comment"] or "",
            source=row["source"] or SOURCE_BUTTON,
            created_at=row["created_at"],
        )


class TransactionService:
    """Создание, изменение, удаление и чтение операций."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # --- валидация -------------------------------------------------------

    @staticmethod
    def validate_amount(amount: Any) -> Decimal:
        try:
            value = to_decimal(amount)
        except ValueError as exc:
            raise TransactionError("Не удалось разобрать сумму.") from exc
        if value <= 0:
            raise TransactionError("Сумма должна быть больше нуля.")
        if value > MAX_AMOUNT:
            raise TransactionError("Слишком большая сумма — проверьте ввод.")
        return value

    @staticmethod
    def validate_type(type_: str) -> str:
        if type_ not in {EXPENSE, INCOME}:
            raise TransactionError("Неизвестный тип операции.")
        return type_

    # --- запись ----------------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        type_: str,
        amount: Any,
        currency: str,
        category_id: int | None = None,
        transaction_date: date | None = None,
        comment: str = "",
        source: str = SOURCE_BUTTON,
        raw_text: str = "",
        tz_name: str | None = None,
    ) -> TransactionRecord:
        """Записать операцию. Проверяет принадлежность категории пользователю."""
        type_ = self.validate_type(type_)
        value = self.validate_amount(amount)
        op_date = transaction_date or today_in_tz(tz_name)

        async with self._db.transaction() as conn:
            if category_id is not None:
                owner_type = await conn.fetchval(
                    "SELECT type FROM categories WHERE id = $1 AND user_id = $2",
                    category_id,
                    user_id,
                )
                if owner_type is None:
                    raise TransactionError("Категория не найдена.")
                if owner_type != type_:
                    raise TransactionError("Категория относится к другому типу операции.")

            row = await conn.fetchrow(
                """
                INSERT INTO transactions (user_id, type, amount, currency, category_id,
                                          transaction_date, comment, source, raw_text,
                                          created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW())
                RETURNING id
                """,
                user_id,
                type_,
                value,
                currency,
                category_id,
                op_date,
                comment[:500],
                source,
                raw_text[:2000],
            )
            record = await conn.fetchrow(
                _SELECT_TX + " WHERE t.id = $1 AND t.user_id = $2", row["id"], user_id
            )

        logger.info(
            "Операция #%s: %s %s %s (категория %s, источник %s)",
            row["id"],
            TRANSACTION_TYPE_LABELS[type_],
            value,
            currency,
            category_id,
            source,
        )
        return TransactionRecord.from_record(record)

    async def update(
        self,
        transaction_id: int,
        user_id: int,
        *,
        amount: Any | None = None,
        category_id: int | None = None,
        comment: str | None = None,
        transaction_date: date | None = None,
        type_: str | None = None,
    ) -> TransactionRecord | None:
        """Изменить операцию (только свою). ``None`` — не найдена."""
        current = await self.get(transaction_id, user_id)
        if current is None:
            return None

        new_type = self.validate_type(type_) if type_ else current.type
        new_amount = self.validate_amount(amount) if amount is not None else current.amount
        new_category = current.category_id if category_id is None else category_id
        new_comment = current.comment if comment is None else comment[:500]
        new_date = transaction_date or current.transaction_date

        async with self._db.transaction() as conn:
            if new_category is not None:
                owner = await conn.fetchrow(
                    "SELECT type FROM categories WHERE id = $1 AND user_id = $2",
                    new_category,
                    user_id,
                )
                if owner is None:
                    raise TransactionError("Категория не найдена.")
                if owner["type"] != new_type:
                    raise TransactionError("Категория относится к другому типу операции.")

            await conn.execute(
                """
                UPDATE transactions
                   SET type = $3, amount = $4, category_id = $5, comment = $6,
                       transaction_date = $7, updated_at = NOW()
                 WHERE id = $1 AND user_id = $2
                """,
                transaction_id,
                user_id,
                new_type,
                new_amount,
                new_category,
                new_comment,
                new_date,
            )
            row = await conn.fetchrow(
                _SELECT_TX + " WHERE t.id = $1 AND t.user_id = $2", transaction_id, user_id
            )
        return TransactionRecord.from_record(row) if row else None

    async def delete(self, transaction_id: int, user_id: int) -> bool:
        """Удалить операцию (только свою)."""
        result = await self._db.execute(
            "DELETE FROM transactions WHERE id = $1 AND user_id = $2", transaction_id, user_id
        )
        return result.endswith("1")

    # --- чтение ----------------------------------------------------------

    async def get(self, transaction_id: int, user_id: int) -> TransactionRecord | None:
        row = await self._db.fetchrow(
            _SELECT_TX + " WHERE t.id = $1 AND t.user_id = $2", transaction_id, user_id
        )
        return TransactionRecord.from_record(row) if row else None

    async def list_period(
        self,
        user_id: int,
        date_range: DateRange,
        *,
        type_: str | None = None,
        category_id: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TransactionRecord]:
        """Операции за период (новые сверху)."""
        rows = await self._db.fetch(
            _SELECT_TX
            + """
             WHERE t.user_id = $1
               AND t.transaction_date BETWEEN $2 AND $3
               AND ($4::text IS NULL OR t.type = $4)
               AND ($5::bigint IS NULL OR t.category_id = $5)
             ORDER BY t.transaction_date DESC, t.created_at DESC
             LIMIT $6 OFFSET $7
            """,
            user_id,
            date_range.start,
            date_range.end,
            type_,
            category_id,
            limit,
            offset,
        )
        return [TransactionRecord.from_record(row) for row in rows]

    async def count_period(
        self,
        user_id: int,
        date_range: DateRange,
        *,
        type_: str | None = None,
    ) -> int:
        value = await self._db.fetchval(
            """
            SELECT COUNT(*) FROM transactions
             WHERE user_id = $1 AND transaction_date BETWEEN $2 AND $3
               AND ($4::text IS NULL OR type = $4)
            """,
            user_id,
            date_range.start,
            date_range.end,
            type_,
        )
        return int(value or 0)

    async def last(self, user_id: int, limit: int = 5) -> list[TransactionRecord]:
        """Последние записанные операции (для быстрых подсказок)."""
        rows = await self._db.fetch(
            _SELECT_TX + " WHERE t.user_id = $1 ORDER BY t.created_at DESC LIMIT $2",
            user_id,
            limit,
        )
        return [TransactionRecord.from_record(row) for row in rows]


