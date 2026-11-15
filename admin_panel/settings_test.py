"""Отдельная конфигурация Django для миграций и тестов.

Особенность окружения: папка проекта содержит кириллицу в пути
(``D:\\Программирование\\Python\\Max``), а Django-конфиг создаёт файлы
с относительными путями. Поэтому BASE_DIR считается от ``__file__``,
а не от текущего каталога.
"""

from __future__ import annotations

import sys
from pathlib import Path

from bot.config import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent

settings = get_settings()

SECRET_KEY = settings.django_secret_key
DEBUG = settings.django_debug
ALLOWED_HOSTS = settings.allowed_hosts or ["localhost", "127.0.0.1"]

# Первый запуск: миграции можно применять без проверки схемы.
if "migrate" in sys.argv or "makemigrations" in sys.argv:
    settings_django_debug = DEBUG
