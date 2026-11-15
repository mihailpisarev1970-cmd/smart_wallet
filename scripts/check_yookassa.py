"""Проверить доступ к API ЮKassa с текущими ключами.

1. ``GET /v3/me`` — информация о магазине (проверка авторизации).
2. Создание тестового платежа на 1 ₽ (без подтверждения — деньги не спишутся).

Отчёт: ``.report/yookassa_check.txt``.
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "yookassa_check.txt"
BASE = "https://api.yookassa.ru/v3"


def main() -> int:
    settings = reload_settings()
    out: list[str] = []

    def log(message: str = "") -> None:
        out.append(message)
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text("\n".join(out), encoding="utf-8")

    shop_id = settings.yookassa_shop_id
    secret = settings.yookassa_secret_key
    log(f"ShopID: {shop_id}")
    log(f"Secret: {secret[:10]}...{secret[-4:] if len(secret) > 14 else ''}")
    log(f"Настроено: {settings.yookassa_configured}")
    log("")

    auth = (shop_id, secret)
    headers = {"Idempotence-Key": str(uuid.uuid4()), "Content-Type": "application/json"}

    with httpx.Client(verify=verify_option(), timeout=45.0, auth=auth) as client:
        # 1. Проверка авторизации
        log("=== 1. GET /v3/me ===")
        try:
            response = client.get(f"{BASE}/me")
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                data = response.json()
                log(json.dumps(data, ensure_ascii=False, indent=2)[:1500])
            else:
                log(response.text[:600])
        except Exception as exc:
            log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

        # 2. Создание платежа на 1 рубль (без подтверждения)
        log("\n=== 2. POST /v3/payments (1 ₽, без подтверждения) ===")
        payload = {
            "amount": {"value": "1.00", "currency": "RUB"},
            "capture": False,
            "confirmation": {
                "type": "redirect",
                "return_url": "https://example.com/return",
            },
            "description": "Проверка интеграции",
        }
        try:
            response = client.post(f"{BASE}/payments", json=payload, headers=headers)
            log(f"HTTP {response.status_code}")
            if response.status_code < 400:
                data = response.json()
                log(f"  id:     {data.get('id')}")
                log(f"  status: {data.get('status')}")
                log(f"  paid:   {data.get('paid')}")
                confirmation = data.get("confirmation") or {}
                log(f"  URL:    {confirmation.get('confirmation_url')}")
                log(f"\n  Полный ответ:\n{json.dumps(data, ensure_ascii=False, indent=2)[:1200]}")
            else:
                log(response.text[:800])
        except Exception as exc:
            log(f"ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
