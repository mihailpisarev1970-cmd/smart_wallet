"""Дашборд владельца: сводка по пользователям, активности и расходам на AI.

Реализован как отдельная страница админки (``/admin/dashboard/``) и ссылка
в заголовке. Все показатели считаются в БД — Django импортируется только здесь,
бот этих моделей не использует (архитектурное правило ТЗ).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone

from wallet.models import AIUsageLog, Subscription, Transaction, User

ZERO = Decimal("0.00")


@staff_member_required
def dashboard_view(request):  # noqa: ANN001, ANN201 - сигнатура Django view
    """Страница со сводной статистикой бота."""
    now = timezone.now()
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    users = User.objects.all()
    transactions = Transaction.objects.all()
    ai_logs = AIUsageLog.objects.all()

    # --- Пользователи ---
    users_stats = {
        "total": users.count(),
        "new_week": users.filter(created_at__gte=week_ago).count(),
        "active_day": users.filter(last_seen_at__gte=day_ago).count(),
        "active_week": users.filter(last_seen_at__gte=week_ago).count(),
        "paid": users.filter(
            ai_subscription_status="paid", ai_subscription_until__gt=now
        ).count(),
        "onboarded": users.filter(onboarding_completed=True).count(),
    }

    # --- Операции ---
    totals = transactions.aggregate(
        income=Sum("amount", filter=Q(type="income")),
        expense=Sum("amount", filter=Q(type="expense")),
    )
    tx_stats = {
        "total": transactions.count(),
        "income": totals["income"] or ZERO,
        "expense": totals["expense"] or ZERO,
        "balance": (totals["income"] or ZERO) - (totals["expense"] or ZERO),
        "week": transactions.filter(created_at__gte=week_ago).count(),
        "by_source": list(
            transactions.values("source").annotate(count=Count("id")).order_by("-count")
        ),
    }

    # --- AI: количество запросов и стоимость ---
    ai_totals = ai_logs.aggregate(
        count=Count("id"),
        cost=Sum("cost_usd"),
        stt=Count("id", filter=Q(request_type="stt")),
        llm=Count("id", filter=Q(request_type__in=["parse", "multi", "assistant"])),
        failed=Count("id", filter=Q(success=False)),
        fallback=Count("id", filter=Q(fallback_used=True)),
    )
    ai_month = ai_logs.filter(created_at__gte=month_ago).aggregate(
        cost=Sum("cost_usd"), count=Count("id")
    )
    ai_stats = {
        "total": ai_totals["count"] or 0,
        "stt": ai_totals["stt"] or 0,
        "llm": ai_totals["llm"] or 0,
        "failed": ai_totals["failed"] or 0,
        "fallback": ai_totals["fallback"] or 0,
        "cost_total": ai_totals["cost"] or ZERO,
        "cost_month": ai_month["cost"] or ZERO,
        "requests_month": ai_month["count"] or 0,
        "by_type": list(
            ai_logs.values("request_type")
            .annotate(count=Count("id"), cost=Sum("cost_usd"))
            .order_by("-count")
        ),
        "by_model": list(
            ai_logs.values("model_used")
            .annotate(count=Count("id"), cost=Sum("cost_usd"))
            .order_by("-count")[:10]
        ),
    }

    # --- Подписки и выручка ---
    subs = Subscription.objects.all()
    subscription_stats = {
        "active": subs.filter(status="active").count(),
        "pending": subs.filter(status="pending").count(),
        "revenue": subs.filter(status="active").aggregate(total=Sum("amount"))["total"] or ZERO,
        "recent": list(subs.select_related("user").order_by("-created_at")[:10]),
    }

    # --- Активность по дням (7 дней) ---
    activity = (
        transactions.filter(created_at__gte=week_ago)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    context = {
        **{"admin": True},
        "title": "Дашборд",
        "users_stats": users_stats,
        "tx_stats": tx_stats,
        "ai_stats": ai_stats,
        "subscription_stats": subscription_stats,
        "activity": list(activity),
        "now": now,
    }
    return render(request, "admin/wallet/dashboard.html", context)
