"""Создание администратора админки (идемпотентно, для локальной проверки).

Запуск::

    python -m scripts.create_admin
    python -m scripts.create_admin --username owner --password <ваш-пароль>

Пароль берётся из ``--password`` или переменной окружения
``DJANGO_SUPERUSER_PASSWORD``. Для production пароль задавайте только
через свои секреты!
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Django-проект лежит в admin_panel/, приложение wallet — внутри него.
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "admin_panel"))


def main(username: str, password: str, email: str) -> int:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")
    import django

    django.setup()

    from django.contrib.auth import get_user_model

    user_model = get_user_model()
    user, created = user_model.objects.get_or_create(
        username=username, defaults={"email": email, "is_staff": True, "is_superuser": True}
    )
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    if email:
        user.email = email
    user.set_password(password)
    user.save()

    report = PROJECT_ROOT / ".report" / "admin_user.txt"
    report.parent.mkdir(exist_ok=True)
    report.write_text(
        f"{'Создан' if created else 'Обновлён'}: {username}\n"
        f"Пароль: {password}\n"
        f"Адрес: http://127.0.0.1:8000/admin/\n",
        encoding="utf-8",
    )
    print(f"{'Создан' if created else 'Обновлён'} администратор: {username}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="owner")
    parser.add_argument("--password", default=os.environ.get("DJANGO_SUPERUSER_PASSWORD", ""))
    parser.add_argument("--email", default="")
    args = parser.parse_args()
    sys.exit(main(args.username, args.password, args.email))
