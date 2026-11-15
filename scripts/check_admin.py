"""Проверка админ-панели: страницы, модели, дашборд (без браузера).

Использует Django test client: логинится администратором и обходит все
разделы админки, проверяя HTTP-коды. Отчёт: ``.report/admin_pages.txt``.

Запуск::

    python -m scripts.check_admin
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "admin_panel"))

REPORT = PROJECT_ROOT / ".report" / "admin_pages.txt"

PAGES = [
    ("/admin/", "Главная админки"),
    ("/admin/dashboard/", "Дашборд"),
    ("/healthz", "Healthcheck"),
    ("/admin/wallet/user/", "Пользователи"),
    ("/admin/wallet/transaction/", "Операции"),
    ("/admin/wallet/category/", "Категории"),
    ("/admin/wallet/budget/", "Бюджеты"),
    ("/admin/wallet/goal/", "Цели"),
    ("/admin/wallet/aiusagelog/", "AI-логи"),
    ("/admin/wallet/subscription/", "Подписки"),
    ("/admin/wallet/processedupdate/", "Обработанные события"),
    ("/admin/wallet/userstate/", "Состояния диалогов"),
]


def main() -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")
    import django

    django.setup()

    from django.contrib.auth import get_user_model
    from django.test import Client

    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    user_model = get_user_model()
    admin_user = user_model.objects.filter(is_superuser=True).first()
    if admin_user is None:
        log("Нет администратора — сначала: python -m scripts.create_admin")
        return 1

    log(f"Вход как: {admin_user.username}\n")

    client = Client()
    client.force_login(admin_user)

    ok = 0
    for url, title in PAGES:
        try:
            response = client.get(url)
        except Exception as exc:
            log(f"[ERR ] {title:28} {url} — {type(exc).__name__}: {exc}")
            continue
        status = response.status_code
        mark = "OK  " if status == 200 else "FAIL"
        if status == 200:
            ok += 1
        extra = ""
        if status == 200 and response.get("Content-Type", "").startswith("text/html"):
            extra = f" ({len(response.content)} байт)"
        log(f"[{mark}] {title:28} {url} → {status}{extra}")

    # Проверяем поиск и фильтры на реальных данных
    log("\nПроверка поиска/фильтров:")
    checks = [
        ("/admin/wallet/user/?q=72910765", "поиск пользователя по max_user_id"),
        ("/admin/wallet/transaction/?type__exact=expense", "фильтр расходов"),
        ("/admin/wallet/transaction/?source__exact=text", "фильтр по источнику text"),
        ("/admin/wallet/aiusagelog/?request_type__exact=stt", "фильтр STT"),
        ("/admin/wallet/subscription/?status__exact=active", "активные подписки"),
    ]
    for url, label in checks:
        response = client.get(url)
        mark = "OK  " if response.status_code == 200 else "FAIL"
        log(f"[{mark}] {label}")

    log(f"\nИтого страниц OK: {ok}/{len(PAGES)}")
    print(out.getvalue())
    return 0 if ok == len(PAGES) else 2


if __name__ == "__main__":
    sys.exit(main())
