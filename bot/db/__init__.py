"""Подключение к PostgreSQL для бота (asyncpg) и транзакции.

Архитектурное правило ТЗ: бот не импортирует Django-модели. Схему создаёт
Django (``migrate``), бот читает и пишет те же таблицы напрямую через
``asyncpg``. Денежные значения передаются как ``Decimal`` — тип ``NUMERIC``
asyncpg возвращает как ``Decimal``, поэтому float не используется.

Использование::

    db = Database(settings.database_url)
    await db.connect()
    user = await db.fetchone("SELECT * FROM users WHERE max_user_id = $1", 123)
    async with db.transaction():
        await db.execute("INSERT INTO ...")
    await db.close()
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from asyncpg import Connection, Pool

logger = logging.getLogger(__name__)


async def _init_connection(conn: Connection) -> None:
    """Кодировать JSON/JSONB как текст (Django ожидает стандартный JSON)."""
    await conn.set_type_codec(
        "json",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "jsonb",
        encoder=json.dumps,
        decoder=json.loads,
        schema="pg_catalog",
    )


@asynccontextmanager
async def transaction(conn: Connection) -> AsyncIterator[Connection]:
    """Транзакция на конкретном соединении (для финансовых операций)."""
    async with conn.transaction():
        yield conn


class Database:
    """Пул соединений с PostgreSQL и небольшая обёртка над asyncpg."""

    def __init__(self, dsn: str, *, min_size: int = 1, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: Pool | None = None

    # --- жизненный цикл -------------------------------------------------

    async def connect(self) -> None:
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
            init=_init_connection,
            command_timeout=30,
        )
        logger.info("Подключение к PostgreSQL установлено (pool %s..%s)", self._min_size, self._max_size)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            logger.info("Пул соединений PostgreSQL закрыт")

    @property
    def pool(self) -> Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() не был вызван")
        return self._pool

    async def check_connection(self) -> tuple[bool, str]:
        """Проверка подключения: (ok, сообщение/версия)."""
        try:
            row = await self.fetchrow("SELECT version() AS version")
        except Exception as exc:
            return False, str(exc)
        return True, str(row["version"]) if row else "?"

    # --- запросы ---------------------------------------------------------

    async def execute(self, query: str, *args: Any, **kwargs: Any) -> str:
        """Выполнить запрос.

        Поддерживает позиционные (``$1``) и именованные (``$name``) параметры:
        asyncpg принимает именованные только одним dict-аргументом.
        """
        async with self.pool.acquire() as conn:
            if kwargs:
                return await conn.execute(query, (args[0] | kwargs) if args else kwargs)
            return await conn.execute(query, *args)

    async def fetch(self, query: str, *args: Any, **kwargs: Any) -> Sequence[asyncpg.Record]:
        async with self.pool.acquire() as conn:
            if kwargs:
                return await conn.fetch(query, (args[0] | kwargs) if args else kwargs)
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any, **kwargs: Any) -> asyncpg.Record | None:
        async with self.pool.acquire() as conn:
            if kwargs:
                return await conn.fetchrow(query, (args[0] | kwargs) if args else kwargs)
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any, **kwargs: Any) -> Any:
        async with self.pool.acquire() as conn:
            if kwargs:
                return await conn.fetchval(query, (args[0] | kwargs) if args else kwargs)
            return await conn.fetchval(query, *args)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Connection]:
        """Транзакция: все финансовые операции ТЗ выполняются внутри неё."""
        async with self.pool.acquire() as conn, conn.transaction():
            yield conn
