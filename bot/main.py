"""Точка входа бота «Умный кошелёк» (MAX).

Запуск::

    python -m bot.main              # режим из .env (local -> long polling)
    python -m bot.main --check      # только проверить окружение и выйти

В режиме ``polling`` бот работает локально и не требует HTTPS/домена.
Для production используется webhook (см. ``webhook_server.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from bot.api import MaxAuthError, MaxClient
from bot.config import get_settings
from bot.db import Database
from bot.dispatcher import build_dispatcher
from bot.logging_setup import setup_logging
from bot.polling import poll_updates
from bot.utils.tls import build_ca_bundle

logger = logging.getLogger(__name__)


async def run_polling(stop_event: asyncio.Event) -> int:
    """Основной цикл бота (long polling)."""
    settings = get_settings()
    build_ca_bundle()  # готовим CA-бандл заранее (сертификаты Минцифры)

    db = Database(
        settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    await db.connect()
    ok, version = await db.check_connection()
    if not ok:
        logger.critical("Нет подключения к PostgreSQL: %s", version)
        await db.close()
        return 2
    logger.info("PostgreSQL: %s", version.split(",")[0])

    async with MaxClient(
        settings.max_bot_token,
        settings.max_api_base_url,
        timeout=settings.max_http_timeout_seconds,
    ) as api:
        me = await api.get_me()
        logger.info(
            "Бот запущен: %s (@%s), user_id=%s",
            me.get("name"),
            me.get("username"),
            me.get("user_id"),
        )

        dispatcher = await build_dispatcher(db, api, settings)

        # Команды в подсказках MAX («/» в диалоге с ботом).
        from bot.commands import register_commands

        await register_commands(api)
        try:
            await poll_updates(
                api,
                dispatcher.handle_update,
                timeout=settings.max_poll_timeout_seconds,
                limit=settings.max_poll_limit,
                stop_event=stop_event,
            )
        except MaxAuthError:
            logger.critical("Токен бота недействителен — проверьте .env")
            return 3
        except asyncio.CancelledError:
            logger.info("Остановка по сигналу")
        finally:
            await db.close()
    return 0


async def check_environment() -> int:
    """Проверка окружения перед запуском (БД, MAX API, ключи AI)."""
    settings = get_settings()
    build_ca_bundle()
    print(f"Окружение: {settings.app_env}, режим апдейтов: {settings.max_updates_mode}")

    db = Database(settings.database_url, min_size=1, max_size=2)
    await db.connect()
    ok, info = await db.check_connection()
    print(f"PostgreSQL: {'OK' if ok else 'ОШИБКА'} — {info[:70]}")
    if ok:
        tables = await db.fetchval(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'"
        )
        print(f"Таблиц в схеме: {tables} (ожидается >= 19 после миграций)")
    await db.close()

    async with MaxClient(settings.max_bot_token, settings.max_api_base_url) as api:
        me = await api.get_me()
        print(f"MAX API: OK — {me.get('name')} (@{me.get('username')})")

    print(f"AI Dostup (LLM): {'настроен' if settings.llm_configured else 'НЕ настроен'}")
    print(f"STT: {'настроен' if settings.stt_configured else 'НЕ настроен'}")
    print(f"Robokassa: {'настроен' if settings.robokassa_configured else 'НЕ настроен'}")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Чат-бот «Умный кошелёк» для MAX")
    parser.add_argument("--check", action="store_true", help="Проверить окружение и выйти")
    parser.add_argument("--log-level", default=None, help="Уровень логирования (INFO/DEBUG)")
    args = parser.parse_args()

    setup_logging(args.log_level)
    if args.check:
        return asyncio.run(check_environment())

    stop_event = asyncio.Event()

    async def runner() -> int:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: stop_event.set())
        return await run_polling(stop_event)

    try:
        return asyncio.run(runner())
    except KeyboardInterrupt:
        print("\nОстановлено пользователем")
        return 0


if __name__ == "__main__":
    sys.exit(main())
