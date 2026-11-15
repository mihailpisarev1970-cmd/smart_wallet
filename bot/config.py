"""Конфигурация приложения.

Все секреты и настройки читаются из `.env` (см. `.env.example`).
Модуль не импортирует Django — бот и админка общаются только через БД.

Использование:
    from bot.config import get_settings

    settings = get_settings()          # кэшированный экземпляр
    settings.max_bot_token
"""

from __future__ import annotations

import functools
import re
from pathlib import Path
from typing import Literal

from pydantic import computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TIMEZONE = "Europe/Moscow"

Currency = Literal["RUB", "USD", "EUR"]

#: Символы, которые часто остаются в .env при копировании из документации
#: (угловые скобки-заглушки, «умные» кавычки, неразрывные пробелы).
_PLACEHOLDER_CHARS = re.compile(r"[<>«»\"'\u00a0\u200b]")


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из окружения / `.env`."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        validate_default=True,
    )

    # --- Окружение -----------------------------------------------------
    app_env: Literal["local", "production"] = "local"
    log_level: str = "INFO"
    log_dir: Path = BASE_DIR / "logs"

    # --- MAX Bot API ---------------------------------------------------
    max_bot_token: str = ""
    max_api_base_url: str = "https://platform-api2.max.ru"
    max_updates_mode: Literal["polling", "webhook"] = "polling"
    max_poll_timeout_seconds: int = 30
    max_poll_limit: int = 100
    max_http_timeout_seconds: float = 40.0

    webhook_base_url: str = ""
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080
    max_webhook_secret: str = ""
    max_webhook_url: str = ""
    robokassa_gateway_token: str = ""

    # --- База данных ---------------------------------------------------
    database_url: str = "postgresql://wallet:wallet@localhost:5432/smart_wallet"
    db_pool_min_size: int = 1
    db_pool_max_size: int = 10

    # --- Django --------------------------------------------------------
    django_secret_key: str = "change-me-in-production"
    django_debug: bool = True
    django_allowed_hosts: str = "localhost,127.0.0.1"
    owner_max_user_id: int | None = None

    # --- LLM (AI Dostup) -----------------------------------------------
    ai_dostup_base_url: str = "https://aidostup.site/v1"
    ai_dostup_api_key: str = ""
    ai_dostup_model: str = "deepseek-v4.1-flash-1017"
    ai_timeout_seconds: float = 30.0
    ai_free_requests: int = 10

    # --- STT -----------------------------------------------------------
    #: Единственная модель распознавания: AI Dostup принимает только её.
    #: ``whisper-1`` удалён провайдером (HTTP 400), fallback невозможен.
    stt_primary_model: str = "gpt-4o-transcribe"
    stt_api_base_url: str = "https://api.openai.com/v1"
    stt_api_key: str = ""
    stt_timeout_seconds: float = 30.0
    stt_max_file_size_mb: int = 25
    stt_language: str = "ru"

    # --- ЮKassa (оплата AI-подписки) ------------------------------------
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""
    ai_subscription_price_rub: int = 210
    ai_subscription_days: int = 30

    # --- Производные значения ------------------------------------------

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.django_allowed_hosts.split(",") if host.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_webhook_path(self) -> str:
        return f"/webhook/max/{self.max_webhook_secret}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def public_max_webhook_url(self) -> str:
        """Публичный адрес вебхука для POST /subscriptions."""
        if self.max_webhook_url:
            return self.max_webhook_url
        if self.webhook_base_url:
            return self.webhook_base_url.rstrip("/") + self.max_webhook_path
        return ""

    # --- Валидация ------------------------------------------------------

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper().strip()

    @field_validator("max_api_base_url", "ai_dostup_base_url", "stt_api_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("owner_max_user_id", mode="before")
    @classmethod
    def _empty_str_to_none(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return value

    @field_validator("max_bot_token", mode="before")
    @classmethod
    def _clean_bot_token(cls, value: object) -> object:
        """Убрать «мусорные» символы, оставшиеся от копирования из документации."""
        if isinstance(value, str):
            return _PLACEHOLDER_CHARS.sub("", value).strip()
        return value

    @field_validator("max_bot_token")
    @classmethod
    def _require_bot_token(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError(
                "MAX_BOT_TOKEN не задан. Укажите токен бота в .env "
                "(Чат-боты → ⋮ → Настройки)."
            )
        return value

    # --- Проверки готовности интеграций ---------------------------------

    @property
    def llm_configured(self) -> bool:
        return bool(self.ai_dostup_api_key)

    @property
    def stt_configured(self) -> bool:
        return bool(self.stt_api_key)

    @property
    def yookassa_configured(self) -> bool:
        """Заданы ли реквизиты ЮKassa для приёма оплаты."""
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Вернуть кэшированный экземпляр настроек."""
    return Settings()


def reload_settings() -> Settings:
    """Сбросить кэш и перечитать `.env` (нужно для тестов)."""
    get_settings.cache_clear()
    return get_settings()
