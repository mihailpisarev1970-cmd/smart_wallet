"""Проверка подключения бота к БД (asyncpg) — без Django.

Запуск::

    python -m scripts.check_db
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import get_settings
from bot.db import Database

EXPECTED_TABLES = (
    "users",
    "categories",
    "transactions",
    "budgets",
    "goals",
    "ai_usage_log",
    "subscriptions",
    "user_states",
    "processed_updates",
)


async def main() -> int:
    settings = get_settings()
    db = Database(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    await db.connect()
    try:
        ok, version = await db.check_connection()
        print(f"Подключение: {'OK' if ok else 'FAIL'} — {version[:60]}")
        if not ok:
            return 1

        rows = await db.fetch(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        tables = {row["table_name"] for row in rows}
        missing = [name for name in EXPECTED_TABLES if name not in tables]
        print(f"Таблиц в схеме: {len(tables)}")
        print("Ожидаемые таблицы: " + ("все на месте" if not missing else f"НЕТ {missing}"))

        # Проверяем, что Decimal приходит как Decimal (ТЗ: float не использовать).
        value = await db.fetchval("SELECT 1500.50::numeric(14,2)")
        print(f"NUMERIC -> {value!r} ({type(value).__name__})")
        return 0 if not missing else 2
    finally:
        await db.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
