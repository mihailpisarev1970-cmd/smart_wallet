"""Справочники проекта: валюты, стандартные категории, часовые пояса.

Категории из ТЗ (п. 3.3, 3.4) дублируются здесь, чтобы бот мог создавать
их при регистрации пользователя без импорта Django-моделей.
"""

from __future__ import annotations

from typing import Final

# --- Валюты ----------------------------------------------------------------

CURRENCY_SYMBOLS: Final[dict[str, str]] = {"RUB": "₽", "USD": "$", "EUR": "€"}
CURRENCIES: Final[tuple[str, ...]] = ("RUB", "USD", "EUR")
DEFAULT_CURRENCY: Final[str] = "RUB"

# --- Типы операций ---------------------------------------------------------

EXPENSE: Final[str] = "expense"
INCOME: Final[str] = "income"
TRANSACTION_TYPES: Final[tuple[str, str]] = (EXPENSE, INCOME)
TRANSACTION_TYPE_LABELS: Final[dict[str, str]] = {EXPENSE: "Расход", INCOME: "Доход"}

# --- Источник операции (для аналитики, ТЗ п. 7.1) --------------------------

SOURCE_BUTTON: Final[str] = "button"
SOURCE_TEXT: Final[str] = "text"
SOURCE_VOICE: Final[str] = "voice"
SOURCES: Final[tuple[str, str, str]] = (SOURCE_BUTTON, SOURCE_TEXT, SOURCE_VOICE)
SOURCE_LABELS: Final[dict[str, str]] = {
    SOURCE_BUTTON: "Кнопки",
    SOURCE_TEXT: "Текст",
    SOURCE_VOICE: "Голос",
}

# --- Стандартные категории (ТЗ п. 3.3, 3.4) --------------------------------

DEFAULT_EXPENSE_CATEGORIES: Final[tuple[str, ...]] = (
    "Продукты",
    "Рестораны и кафе",
    "Транспорт",
    "Автомобиль",
    "Жильё",
    "Коммунальные платежи",
    "Покупки",
    "Здоровье",
    "Развлечения",
    "Образование",
    "Путешествия",
    "Подписки",
    "Другое",
)

DEFAULT_INCOME_CATEGORIES: Final[tuple[str, ...]] = (
    "Зарплата",
    "Подработка",
    "Бизнес",
    "Инвестиции",
    "Подарки",
    "Другие доходы",
)

#: Категория, в которую переносятся операции при удалении категории (ТЗ п. 3.5).
EXPENSE_FALLBACK_CATEGORY: Final[str] = "Другое"
INCOME_FALLBACK_CATEGORY: Final[str] = "Другие доходы"

#: Эмодзи для кнопок меню категорий — только для отображения.
CATEGORY_EMOJI: Final[dict[str, str]] = {
    "Продукты": "🛒",
    "Рестораны и кафе": "🍽",
    "Транспорт": "🚌",
    "Автомобиль": "🚗",
    "Жильё": "🏠",
    "Коммунальные платежи": "💡",
    "Покупки": "🛍",
    "Здоровье": "💊",
    "Развлечения": "🎬",
    "Образование": "📚",
    "Путешествия": "✈️",
    "Подписки": "🔁",
    "Другое": "📦",
    "Зарплата": "💰",
    "Подработка": "🧰",
    "Бизнес": "💼",
    "Инвестиции": "📈",
    "Подарки": "🎁",
    "Другие доходы": "➕",
}

# --- Часовые пояса ---------------------------------------------------------

#: Часовые пояса России + ближайшее зарубежье для экрана выбора.
POPULAR_TIMEZONES: Final[tuple[tuple[str, str], ...]] = (
    ("Europe/Kaliningrad", "Калининград (UTC+2)"),
    ("Europe/Moscow", "Москва (UTC+3)"),
    ("Europe/Samara", "Самара (UTC+4)"),
    ("Asia/Yekaterinburg", "Екатеринбург (UTC+5)"),
    ("Asia/Omsk", "Омск (UTC+6)"),
    ("Asia/Krasnoyarsk", "Красноярск (UTC+7)"),
    ("Asia/Irkutsk", "Иркутск (UTC+8)"),
    ("Asia/Yakutsk", "Якутск (UTC+9)"),
    ("Asia/Vladivostok", "Владивосток (UTC+10)"),
    ("Asia/Magadan", "Магадан (UTC+11)"),
    ("Asia/Kamchatka", "Камчатка (UTC+12)"),
    ("Asia/Almaty", "Алматы (UTC+5)"),
    ("Asia/Tbilisi", "Тбилиси (UTC+4)"),
    ("Asia/Yerevan", "Ереван (UTC+4)"),
    ("Asia/Bishkek", "Бишкек (UTC+6)"),
    ("Asia/Tashkent", "Ташкент (UTC+5)"),
    ("Asia/Dubai", "Дубай (UTC+4)"),
    ("Europe/Istanbul", "Стамбул (UTC+3)"),
    ("Asia/Bangkok", "Бангкок (UTC+7)"),
    ("Europe/Berlin", "Берлин (UTC+1)"),
)

DEFAULT_TIMEZONE: Final[str] = "Europe/Moscow"

# --- Пороговые уведомления бюджета (ТЗ п. 3.9) -----------------------------

BUDGET_THRESHOLDS: Final[tuple[int, ...]] = (50, 80, 100)

# --- Подписка (ТЗ п. 5.3) --------------------------------------------------

SUBSCRIPTION_PLAN_AI: Final[str] = "ai"
SUBSCRIPTION_STATUSES: Final[tuple[str, ...]] = ("pending", "active", "expired", "cancelled")
AI_SUBSCRIPTION_STATUSES: Final[tuple[str, ...]] = ("free", "paid", "expired")

# --- AI --------------------------------------------------------------------

AI_REQUEST_TYPES: Final[tuple[str, ...]] = ("stt", "parse", "multi", "assistant")
AI_REQUEST_LABELS: Final[dict[str, str]] = {
    "stt": "Распознавание речи",
    "parse": "Разбор текста",
    "multi": "Несколько операций",
    "assistant": "AI-помощник",
}

STT_MODELS: Final[tuple[str, ...]] = ("gpt-4o-transcribe",)

#: Форматы аудио, которые принимает STT (ТЗ п. 4.3).
STT_SUPPORTED_FORMATS: Final[tuple[str, ...]] = (
    "flac",
    "mp3",
    "mp4",
    "mpeg",
    "mpga",
    "m4a",
    "ogg",
    "wav",
    "webm",
)
