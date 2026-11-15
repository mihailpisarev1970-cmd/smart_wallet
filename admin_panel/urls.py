"""URL-схема админ-панели.

* ``/admin/`` — Django Admin (владелец);
* ``/admin/dashboard/`` — сводный дашборд;
* ``/``       — редирект в админку;
* ``/healthz``— проверка живости для мониторинга/nginx.
"""

from __future__ import annotations

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path
from django.views.generic import RedirectView

from wallet.dashboard import dashboard_view


def healthz(_request):  # noqa: ANN001, ANN201 - сигнатура Django view
    return JsonResponse({"status": "ok", "service": "smart-wallet-admin"})


urlpatterns = [
    path("", RedirectView.as_view(url="/admin/dashboard/", permanent=False)),
    path("healthz", healthz, name="healthz"),
    path("admin/dashboard/", admin.site.admin_view(dashboard_view), name="dashboard"),
    path("admin/", admin.site.urls),
]

