"""Экраны (состояния) диалога бота.

Каждый экран — это шаг сценария, который бот отрисовал пользователю.
Состояние хранится в БД (``user_states``), поэтому диалог переживает
перезапуск процесса.

Соглашение об именовании: ``<домен>_<шаг>``. Значения — стабильные строки,
они попадают в БД и в payload кнопок, поэтому менять их нужно осторожно.
"""

from __future__ import annotations

from enum import StrEnum


class Screen(StrEnum):
    """Возможные экраны диалога."""

    # --- Онбординг ---
    ONBOARDING_CURRENCY = "onboarding_currency"
    ONBOARDING_TIMEZONE = "onboarding_timezone"

    # --- Главное меню и навигация ---
    MAIN_MENU = "main_menu"

    # --- Добавление расхода/дохода кнопками ---
    TX_KIND = "tx_kind"                  # выбор: расход или доход
    TX_AMOUNT = "tx_amount"              # ввод суммы
    TX_CATEGORY = "tx_category"          # выбор категории
    TX_COMMENT = "tx_comment"            # комментарий (опционально)
    TX_CONFIRM = "tx_confirm"            # подтверждение перед сохранением

    # --- Свободный ввод (текст или голос) ---
    FREE_INPUT = "free_input"

    # --- История ---
    HISTORY_PERIOD = "history_period"
    HISTORY_LIST = "history_list"
    HISTORY_ITEM = "history_item"
    HISTORY_EDIT_FIELD = "history_edit_field"
    HISTORY_EDIT_VALUE = "history_edit_value"
    HISTORY_DELETE_CONFIRM = "history_delete_confirm"
    HISTORY_CUSTOM_FROM = "history_custom_from"
    HISTORY_CUSTOM_TO = "history_custom_to"

    # --- Статистика ---
    STATS_MENU = "stats_menu"

    # --- Бюджеты ---
    BUDGET_MENU = "budget_menu"
    BUDGET_AMOUNT = "budget_amount"
    BUDGET_CATEGORY = "budget_category"
    BUDGET_THRESHOLDS = "budget_thresholds"

    # --- Цели ---
    GOALS_MENU = "goals_menu"
    GOAL_NAME = "goal_name"
    GOAL_TARGET = "goal_target"
    GOAL_DEADLINE = "goal_deadline"
    GOAL_DETAIL = "goal_detail"
    GOAL_CONTRIBUTE = "goal_contribute"
    GOAL_DELETE_CONFIRM = "goal_delete_confirm"

    # --- Настройки ---
    SETTINGS_MENU = "settings_menu"
    SETTINGS_CURRENCY = "settings_currency"
    SETTINGS_TIMEZONE = "settings_timezone"
    SETTINGS_NOTIFICATIONS = "settings_notifications"
    SETTINGS_CATEGORIES = "settings_categories"
    SETTINGS_CATEGORY_ADD_TYPE = "settings_category_add_type"
    SETTINGS_CATEGORY_ADD_NAME = "settings_category_add_name"
    SETTINGS_CATEGORY_MANAGE = "settings_category_manage"
    SETTINGS_CATEGORY_RENAME = "settings_category_rename"
    SETTINGS_CATEGORY_DELETE = "settings_category_delete"
    SETTINGS_EXPORT = "settings_export"
    SETTINGS_DELETE_ACCOUNT = "settings_delete_account"

    # --- AI ---
    AI_MENU = "ai_menu"
    AI_ASSISTANT = "ai_assistant"
    AI_SUBSCRIPTION = "ai_subscription"

    # --- Прочее ---
    HELP = "help"
    ABOUT = "about"
    UNKNOWN = "unknown"


#: Экраны, на которых ожидается текстовый/голосовой ввод свободной формы.
TEXT_INPUT_SCREENS: frozenset[Screen] = frozenset(
    {
        Screen.TX_AMOUNT,
        Screen.TX_COMMENT,
        Screen.HISTORY_EDIT_VALUE,
        Screen.HISTORY_CUSTOM_FROM,
        Screen.HISTORY_CUSTOM_TO,
        Screen.BUDGET_AMOUNT,
        Screen.GOAL_NAME,
        Screen.GOAL_TARGET,
        Screen.GOAL_DEADLINE,
        Screen.GOAL_CONTRIBUTE,
        Screen.SETTINGS_CATEGORY_ADD_NAME,
        Screen.SETTINGS_CATEGORY_RENAME,
        Screen.AI_ASSISTANT,
        Screen.FREE_INPUT,
    }
)
