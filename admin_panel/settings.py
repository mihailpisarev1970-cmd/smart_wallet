"""Настройки Django — только для админ-панели владельца.

Архитектурное правило ТЗ: Django не импортируется ботом, бот не импортирует
Django. Связь — исключительно общая БД PostgreSQL, схему создаёт Django
через ``migrate``.

Переменные окружения читаются из того же ``.env``, что и у бота
(см. ``bot/config.py``). Django использует синхронный драйвер ``psycopg``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from bot.config import get_settings

BASE_DIR = Path(__file__).resolve().parent.parent

settings = get_settings()

SECRET_KEY = settings.django_secret_key
DEBUG = settings.django_debug
ALLOWED_HOSTS = list(settings.allowed_hosts) or ["localhost", "127.0.0.1"]
# Django test client и служебные проверки обращаются к 'testserver'.
if "testserver" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("testserver")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "wallet",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "admin_panel.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "admin_panel" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "admin_panel.wsgi.application"


def _db_config() -> dict[str, object]:
    """Разобрать DATABASE_URL (postgresql://user:pass@host:port/db)."""
    parsed = urlparse(settings.database_url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": (parsed.path or "/smart_wallet").lstrip("/"),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "localhost",
        "PORT": str(parsed.port or 5432),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"connect_timeout": 10},
    }


DATABASES = {"default": _db_config()}

# Тесты Django не должны трогать рабочую БД.
if "test" in sys.argv:
    DATABASES["default"]["TEST"] = {"NAME": "test_smart_wallet"}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "ru-ru"
TIME_ZONE = "Europe/Moscow"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Безопасность (включается автоматически на production) ------------------
if settings.is_production:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    X_FRAME_OPTIONS = "DENY"

# --- Логирование ------------------------------------------------------------
LOG_DIR = settings.log_dir
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname:8} {name}:{lineno} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_DIR / "django.log",
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console", "file"], "level": settings.log_level},
    "loggers": {
        "django.db.backends": {"level": "WARNING"},
    },
}

# --- Параметры проекта, доступные в админке ---------------------------------
OWNER_MAX_USER_ID = settings.owner_max_user_id
AI_SUBSCRIPTION_PRICE_RUB = settings.ai_subscription_price_rub
AI_FREE_REQUESTS = settings.ai_free_requests
