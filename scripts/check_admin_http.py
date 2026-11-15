"""Проверка доступности запущенной админки по HTTP (без браузера).

Запуск::

    python -m scripts.check_admin_http
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request

PROJECT_ROOT_STR = "http://127.0.0.1:8000"
PATHS = (
    ("/healthz", "healthcheck"),
    ("/admin/", "страница входа в админку"),
    ("/admin/dashboard/", "дашборд (редирект на логин)"),
    ("/", "корень (редирект)"),
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Не следовать редиректам, чтобы видеть исходный код ответа."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    opener = urllib.request.build_opener(NoRedirect)
    report = []
    ok = 0
    for path, title in PATHS:
        url = PROJECT_ROOT_STR + path
        try:
            with opener.open(url, timeout=10) as response:
                code = response.status
        except urllib.error.HTTPError as exc:
            code = exc.code
        except Exception as exc:
            report.append(f"[ERR ] {title:34} {path} — {type(exc).__name__}: {exc}")
            continue
        mark = "OK  " if code in (200, 302) else "FAIL"
        if mark == "OK  ":
            ok += 1
        report.append(f"[{mark}] {title:34} {path} → HTTP {code}")

    report.append(f"\nИтого OK: {ok}/{len(PATHS)}")
    text = "\n".join(report)
    from pathlib import Path

    Path(__file__).resolve().parent.parent.joinpath(".report", "admin_http.txt").write_text(
        text, encoding="utf-8"
    )
    print(text)
    return 0 if ok == len(PATHS) else 1


if __name__ == "__main__":
    sys.exit(main())
