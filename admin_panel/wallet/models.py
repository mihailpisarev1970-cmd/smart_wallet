"""Модели БД (владелец схемы — Django, бот пишет через asyncpg).

Таблицы и колонки соответствуют ТЗ п. 7.1. Денежные значения — ``Decimal``
(``NUMERIC(14, 2)``), ``float`` не используется (ТЗ п. 7.2).
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models


class AISubscriptionStatus(models.TextChoices):
    FREE = "free", "Бесплатный"
    PAID = "paid", "Оплачен"
    EXPIRED = "expired", "Истёк"


class User(models.Model):
    """Пользователь бота. ``max_user_id`` — идентификатор из MAX."""

    max_user_id = models.BigIntegerField("ID в MAX", unique=True, db_index=True)
    username = models.CharField("Username", max_length=255, null=True, blank=True)
    first_name = models.CharField("Имя", max_length=255, null=True, blank=True)
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    timezone = models.CharField("Часовой пояс", max_length=64, default="Europe/Moscow")
    language = models.CharField("Язык", max_length=8, default="ru")

    # --- AI-лимиты и подписка (ТЗ п. 5.3) ---
    ai_requests_used = models.PositiveIntegerField("Использовано AI-запросов", default=0)
    ai_subscription_until = models.DateTimeField("Подписка AI до", null=True, blank=True)
    ai_subscription_status = models.CharField(
        "Статус подписки AI",
        max_length=16,
        choices=AISubscriptionStatus.choices,
        default=AISubscriptionStatus.FREE,
    )

    # --- Настройки ---
    notifications_enabled = models.BooleanField("Уведомления включены", default=True)
    onboarding_completed = models.BooleanField("Регистрация завершена", default=False)
    admin_notes = models.TextField("Заметки владельца", blank=True, default="")

    is_active = models.BooleanField("Активен", default=True)
    last_chat_id = models.BigIntegerField(
        "ID последнего чата", null=True, blank=True, db_index=True
    )
    last_seen_at = models.DateTimeField("Последняя активность", null=True, blank=True)
    created_at = models.DateTimeField("Дата регистрации", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "users"
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["is_active", "created_at"], name="ix_users_active_created")]

    def __str__(self) -> str:
        return f"{self.first_name or 'Без имени'} ({self.max_user_id})"


class Category(models.Model):
    """Категория дохода или расхода. Стандартные создаются при регистрации."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="categories", verbose_name="Пользователь"
    )
    name = models.CharField("Название", max_length=64)
    type = models.CharField("Тип", max_length=16, default="expense")
    is_default = models.BooleanField("Стандартная", default=False)
    is_archived = models.BooleanField("В архиве", default=False)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        db_table = "categories"
        verbose_name = "Категория"
        verbose_name_plural = "Категории"
        ordering = ("type", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "type", "name"], name="uq_categories_user_type_name"
            )
        ]
        indexes = [models.Index(fields=["user", "type"], name="ix_categories_user_type")]

    def __str__(self) -> str:
        return f"{self.name} — {'Расход' if self.type == 'expense' else 'Доход'}"


class Transaction(models.Model):
    """Финансовая операция: доход или расход."""

    class Type(models.TextChoices):
        EXPENSE = "expense", "Расход"
        INCOME = "income", "Доход"

    class Source(models.TextChoices):
        BUTTON = "button", "Кнопки"
        TEXT = "text", "Текст"
        VOICE = "voice", "Голос"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="transactions", verbose_name="Пользователь"
    )
    type = models.CharField("Тип", max_length=16, choices=Type.choices, db_index=True)
    amount = models.DecimalField(
        "Сумма",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField("Валюта", max_length=3, default="RUB")
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Категория",
    )
    #: Локальная дата операции (по часовому поясу пользователя).
    transaction_date = models.DateField("Дата операции", db_index=True)
    comment = models.CharField("Комментарий", max_length=500, blank=True, default="")
    source = models.CharField(
        "Источник", max_length=16, choices=Source.choices, default=Source.BUTTON
    )
    #: Для операций, распознанных AI: исходная фраза.
    raw_text = models.TextField("Исходный текст", blank=True, default="")
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "transactions"
        verbose_name = "Операция"
        verbose_name_plural = "Операции"
        ordering = ("-transaction_date", "-created_at")
        indexes = [
            models.Index(fields=["user", "transaction_date"], name="ix_tx_user_date"),
            models.Index(fields=["user", "type", "transaction_date"], name="ix_tx_user_type_date"),
            models.Index(fields=["user", "category"], name="ix_tx_user_category"),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} {self.amount} {self.currency} от {self.transaction_date}"


class Budget(models.Model):
    """Месячный бюджет: общий (``category=None``) или лимит по категории."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="budgets", verbose_name="Пользователь"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="budgets",
        verbose_name="Категория",
    )
    amount = models.DecimalField(
        "Сумма лимита",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    #: Период в формате ``YYYY-MM``.
    period = models.CharField("Период (YYYY-MM)", max_length=7, db_index=True)
    alert_thresholds = models.JSONField("Пороги уведомлений, %", default=list, blank=True)
    sent_thresholds = models.JSONField("Отправленные пороги, %", default=list, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "budgets"
        verbose_name = "Бюджет"
        verbose_name_plural = "Бюджеты"
        ordering = ("-period", "category_id")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "category", "period"], name="uq_budgets_user_category_period"
            )
        ]
        indexes = [models.Index(fields=["user", "period"], name="ix_budgets_user_period")]

    def __str__(self) -> str:
        scope = self.category.name if self.category else "Общий"
        return f"{scope}: {self.amount} ({self.period})"


class Goal(models.Model):
    """Цель накопления."""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="goals", verbose_name="Пользователь"
    )
    name = models.CharField("Название", max_length=128)
    target_amount = models.DecimalField(
        "Целевая сумма",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    saved_amount = models.DecimalField(
        "Накоплено", max_digits=14, decimal_places=2, default=Decimal("0.00")
    )
    deadline = models.DateField("Срок", null=True, blank=True)
    is_completed = models.BooleanField("Достигнута", default=False)
    completed_at = models.DateTimeField("Дата достижения", null=True, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "goals"
        verbose_name = "Цель накопления"
        verbose_name_plural = "Цели накопления"
        ordering = ("is_completed", "deadline", "-created_at")
        indexes = [models.Index(fields=["user", "is_completed"], name="ix_goals_user_completed")]

    def __str__(self) -> str:
        return f"{self.name}: {self.saved_amount}/{self.target_amount}"

    @property
    def progress_percent(self) -> float:
        if not self.target_amount:
            return 0.0
        return float(min(Decimal(100), (self.saved_amount / self.target_amount) * 100))


class AIUsageLog(models.Model):
    """Лог вызовов AI (ТЗ п. 4.2, 7.1): STT и LLM."""

    class RequestType(models.TextChoices):
        STT = "stt", "Распознавание речи"
        PARSE = "parse", "Разбор текста"
        MULTI = "multi", "Несколько операций"
        ASSISTANT = "assistant", "AI-помощник"

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ai_usage",
        verbose_name="Пользователь",
        null=True,
        blank=True,
    )
    request_type = models.CharField(
        "Тип запроса", max_length=16, choices=RequestType.choices, db_index=True
    )
    provider = models.CharField("Провайдер", max_length=32, default="")
    model_used = models.CharField("Модель", max_length=64, default="")
    audio_duration_seconds = models.DecimalField(
        "Длительность аудио, с", max_digits=8, decimal_places=2, null=True, blank=True
    )
    tokens_used = models.IntegerField("Токенов", null=True, blank=True)
    prompt_tokens = models.IntegerField("Входных токенов", null=True, blank=True)
    completion_tokens = models.IntegerField("Выходных токенов", null=True, blank=True)
    cost_usd = models.DecimalField(
        "Стоимость, $", max_digits=12, decimal_places=6, null=True, blank=True
    )
    latency_ms = models.IntegerField("Время ответа, мс", null=True, blank=True)
    success = models.BooleanField("Успешно", default=True)
    error_message = models.TextField("Ошибка", blank=True, default="")
    fallback_used = models.BooleanField("Использован fallback", default=False)
    created_at = models.DateTimeField("Создан", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ai_usage_log"
        verbose_name = "Запрос к AI"
        verbose_name_plural = "Запросы к AI"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["user", "created_at"], name="ix_ai_log_user_created"),
            models.Index(fields=["request_type", "success"], name="ix_ai_log_type_success"),
        ]

    def __str__(self) -> str:
        model = self.model_used or "-"
        return f"{self.get_request_type_display()} / {model} @ {self.created_at:%d.%m.%Y %H:%M}"


class Subscription(models.Model):
    """Платная подписка на AI-функции (ТЗ п. 5.3, 7.1)."""

    class Plan(models.TextChoices):
        AI = "ai", "AI-функции"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает оплаты"
        ACTIVE = "active", "Активна"
        EXPIRED = "expired", "Истекла"
        CANCELLED = "cancelled", "Отменена"

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="subscriptions", verbose_name="Пользователь"
    )
    plan = models.CharField("План", max_length=16, choices=Plan.choices, default=Plan.AI)
    started_at = models.DateTimeField("Начало", null=True, blank=True)
    expires_at = models.DateTimeField("Окончание", null=True, blank=True)
    payment_provider = models.CharField(
        "Платёжный провайдер", max_length=32, default="robokassa"
    )
    external_payment_id = models.CharField(
        "ID платежа (InvId)", max_length=64, null=True, blank=True
    )
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        "Статус", max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "subscriptions"
        verbose_name = "Подписка"
        verbose_name_plural = "Подписки"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["external_payment_id"], name="ix_subs_external_payment_id"),
            models.Index(fields=["user", "status"], name="ix_subs_user_status"),
        ]
        constraints = [
            # Повторный InvId не должен активировать подписку дважды (ТЗ п. 12).
            models.UniqueConstraint(
                fields=["external_payment_id"],
                condition=models.Q(external_payment_id__isnull=False),
                name="uq_subs_external_payment_id",
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} — {self.get_status_display()} ({self.external_payment_id or '—'})"


class UserState(models.Model):
    """Текущее состояние диалога (FSM) и черновик незавершённой операции.

    Хранится в БД, чтобы незавершённый диалог пережил перезапуск бота.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="state",
        verbose_name="Пользователь",
    )
    screen = models.CharField("Экран", max_length=64, default="main_menu")
    data = models.JSONField("Данные состояния", default=dict, blank=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        db_table = "user_states"
        verbose_name = "Состояние диалога"
        verbose_name_plural = "Состояния диалогов"

    def __str__(self) -> str:
        return f"{self.user}: {self.screen}"


class ProcessedUpdate(models.Model):
    """Обработанные события MAX — защита от повторной обработки (ТЗ п. 8, 11)."""

    update_id = models.CharField("ID события", max_length=128, unique=True)
    update_type = models.CharField("Тип события", max_length=32, default="")
    user_max_id = models.BigIntegerField("ID пользователя MAX", null=True, blank=True)
    created_at = models.DateTimeField("Обработано", auto_now_add=True, db_index=True)

    class Meta:
        db_table = "processed_updates"
        verbose_name = "Обработанное событие"
        verbose_name_plural = "Обработанные события"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["created_at"], name="ix_processed_updates_created")]

    def __str__(self) -> str:
        return f"{self.update_type}:{self.update_id}"



