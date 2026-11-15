"""WSGI-точка входа Django (для gunicorn/uwsgi на сервере)."""

from __future__ import annotations

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "admin_panel.settings")

application = get_wsgi_application()
