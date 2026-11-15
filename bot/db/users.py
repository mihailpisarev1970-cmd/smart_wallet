"""Репозитории пользователей и категорий.

Работают с таблицами ``users``, ``categories`` (схема — см.
``admin_panel/wallet/models.py``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from bot.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_EXPENSE_CATEGORIES,
    DEFAULT_INCOME_CATEGORIES,
    DEFAULT_TIMEZONE,
    EXPENSE,
    INCOME,
)
from bot.db import Database

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class UserRecord:
    """Пользователь бота (плоское представление строки ``users``)."""

    id: int
    max_user_id: int
    username: str | None
    first_name: str | None
    currency: str
    timezone: str
    ai_requests_used: int
    ai_subscription_status: str
    ai_subscription_until: Any
    notifications_enabled: bool
    onboarding_completed: bool
    is_active: bool

    @classmethod
    def from_record(cls, row: Any) -> UserRecord:
        return cls(
            id=row["id"],
            max_user_id=row["max_user_id"],
            username=row["username"],
            first_name=row["first_name"],
            currency=row["currency"],
            timezone=row["timezone"],
            ai_requests_used=row["ai_requests_used"],
            ai_subscription_status=row["ai_subscription_status"],
            ai_subscription_until=row["ai_subscription_until"],
            notifications_enabled=row["notifications_enabled"],
            onboarding_completed=row["onboarding_completed"],
            is_active=row["is_active"],
        )

    @property
    def display_name(self) -> str:
        return self.first_name or self.username or "друг"


@dataclass(slots=True)
class CategoryRecord:
    """Категория дохода или расхода."""

    id: int
    user_id: int
    name: str
    type: str
    is_default: bool
    is_archived: bool

    @classmethod
    def from_record(cls, row: Any) -> CategoryRecord:
        return cls(
            id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            type=row["type"],
            is_default=row["is_default"],
            is_archived=row["is_archived"],
        )


class UserRepository:
    """Пользователи бота."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_max_id(self, max_user_id: int) -> UserRecord | None:
        row = await self._db.fetchrow("SELECT * FROM users WHERE max_user_id = $1", max_user_id)
        return UserRecord.from_record(row) if row else None

    async def get_by_id(self, user_id: int) -> UserRecord | None:
        row = await self._db.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return UserRecord.from_record(row) if row else None

    async def set_last_chat_id(self, user_id: int, chat_id: int | None) -> None:
        """Запомнить chat_id диалога — нужен для восстановления голосовых."""
        if not chat_id:
            return
        await self._db.execute(
            "UPDATE users SET last_chat_id = $2, updated_at = NOW() WHERE id = $1",
            user_id,
            int(chat_id),
        )

    async def recent_chat_ids(self, limit: int = 10) -> list[int]:
        """chat_id пользователей, активных недавно (для восстановления событий).

        MAX присылает голосовые без ``chat_id``, поэтому единственный способ
        найти нужный диалог — перебрать чаты недавно активных пользователей.
        """
        rows = await self._db.fetch(
            """
            SELECT last_chat_id
              FROM users
             WHERE last_chat_id IS NOT NULL
               AND is_active = TRUE
             ORDER BY COALESCE(last_seen_at, updated_at) DESC
             LIMIT $1
            """,
            limit,
        )
        return [int(row["last_chat_id"]) for row in rows if row["last_chat_id"]]


    async def ensure_user(
        self,
        max_user_id: int,
        *,
        username: str | None = None,
        first_name: str | None = None,
    ) -> tuple[UserRecord, bool]:
        """Найти или создать пользователя. Возвращает ``(user, created)``.

        При создании сразу заполняются стандартные категории доходов и расходов,
        чтобы пользователь мог записывать операции с первой секунды.
        """
        existing = await self.get_by_max_id(max_user_id)
        if existing:
            await self._db.execute(
                """
                UPDATE users
                   SET last_seen_at = NOW(),
                       username = COALESCE($2, username),
                       first_name = COALESCE($3, first_name),
                       updated_at = NOW()
                 WHERE id = $1
                """,
                existing.id,
                username,
                first_name,
            )
            if username or first_name:
                existing.username = username or existing.username
                existing.first_name = first_name or existing.first_name
            return existing, False

        async with self._db.transaction() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (max_user_id, username, first_name, currency, timezone,
                                   language, ai_requests_used, ai_subscription_until,
                                   ai_subscription_status,
                                   notifications_enabled, onboarding_completed, is_active,
                                   admin_notes, last_seen_at, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, 'ru', 0, NULL, 'free',
                        TRUE, FALSE, TRUE, '', NOW(), NOW(), NOW())
                ON CONFLICT (max_user_id) DO NOTHING
                RETURNING *
                """,
                max_user_id,
                username,
                first_name,
                DEFAULT_CURRENCY,
                DEFAULT_TIMEZONE,
            )
            if row is None:
                # Гонка двух событий одновременно — пользователь уже создан.
                row = await conn.fetchrow(
                    "SELECT * FROM users WHERE max_user_id = $1", max_user_id
                )
                return UserRecord.from_record(row), False

            await CategoryRepository.insert_defaults(conn, row["id"])

        logger.info("Зарегистрирован пользователь MAX %s (id=%s)", max_user_id, row["id"])
        return UserRecord.from_record(row), True

    async def complete_onboarding(self, user_id: int, currency: str, timezone: str) -> None:
        await self._db.execute(
            """
            UPDATE users
               SET currency = $2, timezone = $3, onboarding_completed = TRUE, updated_at = NOW()
             WHERE id = $1
            """,
            user_id,
            currency,
            timezone,
        )

    async def update_settings(self, user_id: int, **fields: Any) -> None:
        """Обновить разрешённые настройки пользователя."""
        allowed = {
            "currency",
            "timezone",
            "notifications_enabled",
            "first_name",
            "username",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return
        # Порядок аргументов фиксирован порядком ключей в dict (Python 3.7+).
        assignments = ", ".join(
            f"{key} = ${index + 2}" for index, key in enumerate(updates)
        )
        await self._db.execute(
            f"UPDATE users SET {assignments}, updated_at = NOW() WHERE id = $1",
            user_id,
            *updates.values(),
        )

    async def delete_user(self, user_id: int) -> None:
        """Удалить аккаунт и все связанные данные (ТЗ п. 3.11, 11)."""
        await self._db.execute("DELETE FROM users WHERE id = $1", user_id)
        logger.info("Удалён аккаунт пользователя id=%s и все его данные", user_id)

    async def touch(self, user_id: int) -> None:
        await self._db.execute("UPDATE users SET last_seen_at = NOW() WHERE id = $1", user_id)


class CategoryRepository:
    """Категории доходов и расходов."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    async def insert_defaults(conn: Any, user_id: int) -> None:
        """Создать стандартные категории для нового пользователя."""
        payload = [(user_id, name, EXPENSE) for name in DEFAULT_EXPENSE_CATEGORIES]
        payload += [(user_id, name, INCOME) for name in DEFAULT_INCOME_CATEGORIES]
        await conn.executemany(
            """
            INSERT INTO categories (user_id, name, type, is_default, is_archived, created_at)
            VALUES ($1, $2, $3, TRUE, FALSE, NOW())
            ON CONFLICT (user_id, type, name) DO NOTHING
            """,
            payload,
        )

    async def list_for_user(
        self, user_id: int, type_: str, *, include_archived: bool = False
    ) -> list[CategoryRecord]:
        rows = await self._db.fetch(
            """
            SELECT id, user_id, name, type, is_default, is_archived
              FROM categories
             WHERE user_id = $1 AND type = $2 AND ($3::bool OR is_archived = FALSE)
             ORDER BY is_default DESC, name
            """,
            user_id,
            type_,
            include_archived,
        )
        return [CategoryRecord.from_record(row) for row in rows]

    async def get(self, category_id: int, user_id: int) -> CategoryRecord | None:
        """Получить категорию, проверив принадлежность пользователю."""
        row = await self._db.fetchrow(
            """
            SELECT id, user_id, name, type, is_default, is_archived
              FROM categories WHERE id = $1 AND user_id = $2
            """,
            category_id,
            user_id,
        )
        return CategoryRecord.from_record(row) if row else None

    async def find_by_name(self, user_id: int, type_: str, name: str) -> CategoryRecord | None:
        row = await self._db.fetchrow(
            """
            SELECT id, user_id, name, type, is_default, is_archived
              FROM categories
             WHERE user_id = $1 AND type = $2 AND lower(name) = lower($3)
             LIMIT 1
            """,
            user_id,
            type_,
            name,
        )
        return CategoryRecord.from_record(row) if row else None

    async def create(self, user_id: int, name: str, type_: str) -> CategoryRecord | None:
        """Создать категорию. ``None`` — категория с таким именем уже есть."""
        row = await self._db.fetchrow(
            """
            INSERT INTO categories (user_id, name, type, is_default, is_archived, created_at)
            VALUES ($1, $2, $3, FALSE, FALSE, NOW())
            ON CONFLICT (user_id, type, name) DO NOTHING
            RETURNING id, user_id, name, type, is_default, is_archived
            """,
            user_id,
            name.strip()[:64],
            type_,
        )
        return CategoryRecord.from_record(row) if row else None

    async def rename(self, category_id: int, user_id: int, new_name: str) -> bool:
        result = await self._db.execute(
            "UPDATE categories SET name = $3 WHERE id = $1 AND user_id = $2",
            category_id,
            user_id,
            new_name.strip()[:64],
        )
        return result.endswith("1")

    async def delete_and_reassign(self, category_id: int, user_id: int) -> tuple[bool, int]:
        """Удалить категорию, перенеся её операции в «Другое»/«Другие доходы».

        ТЗ п. 3.5: удаление категории не должно удалять операции.
        Возвращает ``(успех, сколько операций перенесено)``.
        """
        category = await self.get(category_id, user_id)
        if category is None:
            return False, 0

        from bot.constants import EXPENSE_FALLBACK_CATEGORY, INCOME_FALLBACK_CATEGORY

        fallback_name = (
            EXPENSE_FALLBACK_CATEGORY if category.type == EXPENSE else INCOME_FALLBACK_CATEGORY
        )
        async with self._db.transaction() as conn:
            fallback_id = await conn.fetchval(
                """
                SELECT id FROM categories
                 WHERE user_id = $1 AND type = $2 AND lower(name) = lower($3)
                 LIMIT 1
                """,
                user_id,
                category.type,
                fallback_name,
            )
            if fallback_id is None:
                fallback_id = await conn.fetchval(
                    """
                    INSERT INTO categories (user_id, name, type, is_default, is_archived, created_at)
                    VALUES ($1, $2, $3, TRUE, FALSE, NOW())
                    ON CONFLICT (user_id, type, name) DO UPDATE SET name = EXCLUDED.name
                    RETURNING id
                    """,
                    user_id,
                    fallback_name,
                    category.type,
                )
            if fallback_id == category_id:
                # Нельзя удалить саму «запасную» категорию.
                return False, 0

            moved = await conn.execute(
                "UPDATE transactions SET category_id = $3, updated_at = NOW() "
                "WHERE category_id = $1 AND user_id = $2",
                category_id,
                user_id,
                fallback_id,
            )
            # Лимиты бюджета по удаляемой категории больше не нужны.
            await conn.execute(
                "DELETE FROM budgets WHERE category_id = $1 AND user_id = $2",
                category_id,
                user_id,
            )
            await conn.execute(
                "DELETE FROM categories WHERE id = $1 AND user_id = $2",
                category_id,
                user_id,
            )
        moved_count = int(moved.split()[-1]) if moved else 0
        return True, moved_count


