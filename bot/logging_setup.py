"""Настройка логирования бота.

Пишем в консоль и в файл ``logs/bot.log`` с ротацией. Формат включает время,
уровень, модуль и номер строки — удобно для отладки и разбора инцидентов.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from bot.config import get_settings

LOG_FORMAT = "{asctime} {levelname:8} {name}:{lineno} {message}"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str | None = None) -> None:
    """Инициализировать логирование (идемпотентно)."""
    settings = get_settings()
    log_level = (level or settings.log_level).upper()

    root = logging.getLogger()
    if getattr(root, "_smart_wallet_configured", False):
        return

    formatter = logging.Formatter(LOG_FORMAT, style="{", datefmt=DATE_FORMAT)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root.addHandler(console)

    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.log_dir / "bot.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("Не удалось открыть файл логов: %s", exc)

    root.setLevel(log_level)
    # Сторонние библиотеки не должны забивать лог.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)

    root._smart_wallet_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).info("Логирование настроено: уровень %s", log_level)
