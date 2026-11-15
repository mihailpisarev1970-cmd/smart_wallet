"""Django Admin — панель владельца бота (ТЗ п. 10).

Разделы:
* **Пользователи** — поиск по ``max_user_id``, ручная активация/продление подписки;
* **Операции** — фильтры по типу, категории, дате, пользователю, источнику;
* **Категории, бюджеты, цели** — просмотр;
* **AI-логи** — STT (модель, длительность, стоимость) и LLM (токены, стоимость);
* **Подписки** — статус, дата окончания, история платежей (InvId).

Доступ: только сотрудники (создаются через ``createsuperuser``).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from wallet.models import (
    AIUsageLog,
    Budget,
    Category,
    Goal,
    ProcessedUpdate,
    Subscription,
    Transaction,
    User,
    UserState,
)

admin.site.site_header = "Умный кошелёк — админ-панель"
admin.site.site_title = "Умный кошелёк"
admin.site.index_title = "Управление ботом"


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------


class SubscriptionInline(admin.TabularInline):
    """История подписок пользователя."""

    model = Subscription
    extra = 0
    fields = ("plan", "status", "amount", "started_at", "expires_at", "external_payment_id")
    ordering = ("-created_at",)
    verbose_name_plural = "Подписки"


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Пользователи бота: поиск по `max_user_id`, ручное управление подпиской."""

    list_display = (
        "id",
        "max_user_id",
        "display_name",
        "currency",
        "timezone",
        "ai_requests_used",
        "subscription_badge",
        "transactions_count",
        "created_at",
    )
    list_filter = ("is_active", "onboarding_completed", "ai_subscription_status", "currency")
    search_fields = ("max_user_id", "username", "first_name")
    readonly_fields = ("created_at", "updated_at", "last_seen_at")
    date_hierarchy = "created_at"
    list_per_page = 50
    inlines = (SubscriptionInline,)

    fieldsets = (
        ("Идентификация", {"fields": ("max_user_id", "username", "first_name", "language")}),
        (
            "Настройки",
            {
                "fields": (
                    "currency",
                    "timezone",
                    "notifications_enabled",
                    "onboarding_completed",
                    "is_active",
                )
            },
        ),
        (
            "AI и подписка",
            {
                "fields": (
                    "ai_requests_used",
                    "ai_subscription_status",
                    "ai_subscription_until",
                ),
                "description": "Подписку можно активировать вручную действиями в списке.",
            },
        ),
        ("Служебное", {"fields": ("last_seen_at", "created_at", "updated_at", "admin_notes")}),
    )

    actions = (
        "activate_subscription_30",
        "activate_subscription_90",
        "deactivate_subscription",
        "reset_ai_counter",
    )

    def get_queryset(self, request):  # noqa: ANN001, ANN201 - сигнатура Django
        queryset = super().get_queryset(request)
        return queryset.annotate(_tx_count=Count("transactions", distinct=True))

    @admin.display(description="Имя")
    def display_name(self, obj: User) -> str:
        return obj.first_name or obj.username or "—"

    @admin.display(description="Операций")
    def transactions_count(self, obj: User) -> int:
        return getattr(obj, "_tx_count", 0)

    @admin.display(description="Подписка")
    def subscription_badge(self, obj: User) -> str:
        if obj.ai_subscription_status == "paid" and obj.ai_subscription_until:
            active = obj.ai_subscription_until > timezone.now()
            color = "#1a7f37" if active else "#9a6700"
            label = "активна" if active else "истекла"
            return format_html(
                '<b style="color:{}">{}</b><br><small>до {}</small>',
                color,
                label,
                obj.ai_subscription_until.strftime("%d.%m.%Y"),
            )
        if obj.ai_subscription_status == "expired":
            return mark_safe('<span style="color:#9a6700">истекла</span>')  # noqa: S308
        return mark_safe('<span style="color:#57606a">бесплатный</span>')  # noqa: S308

    # --- действия: ручная активация подписки (ТЗ п. 6: «первая версия») ----

    @admin.action(description="Активировать/продлить подписку на 30 дней")
    def activate_subscription_30(self, request, queryset):  # noqa: ANN001, ANN201
        self._extend(queryset, 30, request)

    @admin.action(description="Активировать/продлить подписку на 90 дней")
    def activate_subscription_90(self, request, queryset):  # noqa: ANN001, ANN201
        self._extend(queryset, 90, request)

    @admin.action(description="Отключить подписку AI")
    def deactivate_subscription(self, request, queryset):  # noqa: ANN001, ANN201
        updated = queryset.update(ai_subscription_status="expired", updated_at=timezone.now())
        self.message_user(
            request, f"Подписка отключена у {updated} пользователей.", messages.SUCCESS
        )

    @admin.action(description="Сбросить счётчик AI-запросов")
    def reset_ai_counter(self, request, queryset):  # noqa: ANN001, ANN201
        updated = queryset.update(ai_requests_used=0, updated_at=timezone.now())
        self.message_user(
            request, f"Счётчик AI сброшен у {updated} пользователей.", messages.SUCCESS
        )

    def _extend(self, queryset, days: int, request) -> None:  # noqa: ANN001
        """Продлить подписку: отсчёт от текущей даты или от активного срока."""
        now = timezone.now()
        count = 0
        for user in queryset:
            current = user.ai_subscription_until
            base = current if current and current > now else now
            user.ai_subscription_until = base + timedelta(days=days)
            user.ai_subscription_status = "paid"
            user.save(
                update_fields=["ai_subscription_until", "ai_subscription_status", "updated_at"]
            )
            count += 1
        self.message_user(
            request,
            f"Подписка активирована/продлена у {count} пользователей (на {days} дней).",
            messages.SUCCESS,
        )


# ---------------------------------------------------------------------------
# Операции
# ---------------------------------------------------------------------------


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Операции с фильтрами по типу, категории, дате, пользователю, источнику."""

    list_display = (
        "id",
        "user",
        "type",
        "amount_display",
        "category",
        "transaction_date",
        "source",
        "comment_short",
        "created_at",
    )
    list_filter = (
        "type",
        "source",
        "transaction_date",
        "category",
        ("user", admin.RelatedOnlyFieldListFilter),
    )
    search_fields = ("comment", "raw_text", "user__max_user_id", "user__first_name")
    date_hierarchy = "transaction_date"
    list_per_page = 100
    list_select_related = ("user", "category")
    autocomplete_fields = ("category",)
    readonly_fields = ("created_at", "updated_at", "raw_text")

    fields = (
        "user",
        "type",
        "amount",
        "currency",
        "category",
        "transaction_date",
        "comment",
        "source",
        "raw_text",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Сумма", ordering="amount")
    def amount_display(self, obj: Transaction) -> str:
        """Сумма со знаком и цветом: красный — расход, зелёный — доход."""
        color = "#cf222e" if obj.type == "expense" else "#1a7f37"
        sign = "−" if obj.type == "expense" else "+"
        formatted = f"{obj.amount:,.2f}".replace(",", " ").replace(".", ",")
        if formatted.endswith(",00"):
            formatted = formatted[:-3]
        return format_html(
            '<b style="color:{}">{}{} {}</b>', color, sign, formatted, obj.currency
        )

    @admin.display(description="Комментарий")
    def comment_short(self, obj: Transaction) -> str:
        return (obj.comment or "—")[:60]


# ---------------------------------------------------------------------------
# Категории, бюджеты, цели — просмотр
# ---------------------------------------------------------------------------


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "type", "user", "is_default", "is_archived", "created_at")
    list_filter = ("type", "is_default", "is_archived")
    search_fields = ("name", "user__max_user_id")
    list_select_related = ("user",)
    list_per_page = 100


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "category", "amount", "period", "created_at")
    list_filter = ("period",)
    search_fields = ("user__max_user_id", "category__name")
    list_select_related = ("user", "category")
    readonly_fields = ("sent_thresholds", "created_at", "updated_at")


@admin.register(Goal)
class GoalAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "name",
        "target_amount",
        "saved_amount",
        "progress",
        "deadline",
        "is_completed",
    )
    list_filter = ("is_completed",)
    search_fields = ("name", "user__max_user_id")
    list_select_related = ("user",)

    @admin.display(description="Прогресс")
    def progress(self, obj: Goal) -> str:
        return f"{obj.progress_percent:.0f}%"


# ---------------------------------------------------------------------------
# AI-логи (STT + LLM)
# ---------------------------------------------------------------------------


@admin.register(AIUsageLog)
class AIUsageLogAdmin(admin.ModelAdmin):
    """Лог вызовов AI: модель, длительность аудио, токены, стоимость, успешность."""

    list_display = (
        "id",
        "created_at",
        "user",
        "request_type",
        "model_used",
        "audio_duration_seconds",
        "tokens_used",
        "cost_usd",
        "success_badge",
        "latency_ms",
        "fallback_used",
    )
    list_filter = (
        "request_type",
        "success",
        "fallback_used",
        ("user", admin.RelatedOnlyFieldListFilter),
        ("created_at", admin.DateFieldListFilter),
    )
    search_fields = ("model_used", "provider", "user__max_user_id", "error_message")
    date_hierarchy = "created_at"
    list_per_page = 100
    list_select_related = ("user",)
    readonly_fields = [field.name for field in AIUsageLog._meta.fields]

    @admin.display(description="Статус")
    def success_badge(self, obj: AIUsageLog) -> str:
        if obj.success:
            return mark_safe('<b style="color:#1a7f37">OK</b>')  # noqa: S308
        return mark_safe('<b style="color:#cf222e">ошибка</b>')  # noqa: S308

    def has_add_permission(self, request) -> bool:  # noqa: ANN001
        return False

    def has_change_permission(self, request, obj=None) -> bool:  # noqa: ANN001
        return False


# ---------------------------------------------------------------------------
# Подписки
# ---------------------------------------------------------------------------


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    """Статус подписок, дата окончания, история платежей по InvId."""

    list_display = (
        "id",
        "user",
        "plan",
        "status",
        "amount",
        "started_at",
        "expires_at",
        "external_payment_id",
        "created_at",
    )
    list_filter = ("status", "plan", "payment_provider", ("created_at", admin.DateFieldListFilter))
    search_fields = ("external_payment_id", "user__max_user_id", "user__first_name")
    date_hierarchy = "created_at"
    list_select_related = ("user",)
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 100


# ---------------------------------------------------------------------------
# Служебные таблицы (только просмотр)
# ---------------------------------------------------------------------------


@admin.register(ProcessedUpdate)
class ProcessedUpdateAdmin(admin.ModelAdmin):
    """Обработанные события MAX — защита от повторной обработки."""

    list_display = ("update_id", "update_type", "user_max_id", "created_at")
    list_filter = ("update_type",)
    search_fields = ("update_id", "user_max_id")
    date_hierarchy = "created_at"
    readonly_fields = ("update_id", "update_type", "user_max_id", "created_at")

    def has_add_permission(self, request) -> bool:  # noqa: ANN001
        return False


@admin.register(UserState)
class UserStateAdmin(admin.ModelAdmin):
    """Текущее состояние диалога (FSM)."""

    list_display = ("user", "screen", "updated_at")
    search_fields = ("user__max_user_id", "screen")
    readonly_fields = ("user", "screen", "data", "updated_at")

    def has_add_permission(self, request) -> bool:  # noqa: ANN001
        return False


