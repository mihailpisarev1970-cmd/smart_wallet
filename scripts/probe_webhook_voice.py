"""Диагностика: приходит ли голосовое сообщение с полем ``message`` через webhook.

Long polling теряет тело голосового (приходит только ``timestamp``).
Проверяем гипотезу: через **webhook** MAX присылает полное сообщение с
вложением ``audio``.

Сценарий:
1. поднимаем локальный HTTP-сервер на ``WEBHOOK_TEST_PORT``;
2. регистрируем webhook ``POST /subscriptions``;
3. просим пользователя отправить голосовое;
4. печатаем **сырое** тело каждого входящего события;
5. отписываемся (``DELETE /subscriptions``) через ``WEBHOOK_KEEP_SECONDS``.

Запуск::

    python -m scripts.probe_webhook_voice
"""

from __future__ import annotations

import io
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "webhook_voice.txt"
PORT = 8099
KEEP_SECONDS = 120


class Collector(BaseHTTPRequestHandler):
    """Принимает события MAX и складывает их в список."""

    events: ClassVar[list[dict]] = []
    lock: ClassVar[threading.Lock] = threading.Lock()

    def log_message(self, fmt: str, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            payload = {"_raw": raw.decode("utf-8", errors="replace")}
        with Collector.lock:
            Collector.events.append(payload)
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


def main() -> int:
    settings = get_settings()
    base = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log(f"Локальный сервер слушает 0.0.0.0:{PORT}")

    with httpx.Client(timeout=httpx.Timeout(20.0), verify=verify_option(), headers=headers) as client:
        # Публичный HTTPS-адрес обязателен для webhook MAX.
        public_url = input("Введите публичный HTTPS URL (например https://xxxx.ngrok-free.app): ").strip()
        if not public_url:
            log("URL не задан — выход")
            server.shutdown()
            return 1
        webhook_url = public_url.rstrip("/") + "/max/webhook"
        log(f"Регистрирую webhook: {webhook_url}")

        response = client.post(f"{base}/subscriptions", json={"url": webhook_url})
        log(f"POST /subscriptions → HTTP {response.status_code}: {response.text[:300]}")
        if response.status_code >= 400:
            server.shutdown()
            return 2

        log(f"\nТеперь отправьте боту ГОЛОСОВОЕ сообщение. Ждём {KEEP_SECONDS} секунд…")
        deadline = time.time() + KEEP_SECONDS
        while time.time() < deadline:
            time.sleep(2)

        with Collector.lock:
            events = list(Collector.events)
        log(f"\nПолучено событий: {len(events)}")
        for index, event in enumerate(events, 1):
            update_type = event.get("update_type")
            has_message = bool(event.get("message"))
            log(f"\n--- Событие {index}: {update_type}, has_message={has_message} ---")
            log(json.dumps(event, ensure_ascii=False, indent=2)[:2500])

        response = client.delete(f"{base}/subscriptions", params={"url": webhook_url})
        log(f"\nDELETE /subscriptions → HTTP {response.status_code}")

    server.shutdown()
    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
