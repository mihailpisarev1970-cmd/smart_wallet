"""Проверить тестовый магазин ЮKassa (ASCII output).

    python -m scripts.check_yk_test
"""

from __future__ import annotations

import base64
import json
import sys
import urllib.request
import uuid

SHOP_ID = "1525878"
SECRET = "test_7taKEcRBSKsTDQaeOV4zVIveIr-8PBNHHY36kXU0WKk"
BASE = "https://api.yookassa.ru/v3"


def auth_header() -> dict[str, str]:
    token = base64.b64encode(f"{SHOP_ID}:{SECRET}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body else None
    headers = auth_header()
    if method == "POST":
        headers["Idempotence-Key"] = str(uuid.uuid4())
    request = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")[:400]
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def main() -> int:
    print("=== 1. GET /me ===")
    code, data = call("GET", "/me")
    print(f"  HTTP {code}")
    print(f"  {json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data}")

    print()
    print("=== 2. POST /payments (1 RUB, test shop) ===")
    code, data = call(
        "POST",
        "/payments",
        {
            "amount": {"value": "1.00", "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": "https://wallet.pisarev-n8n.ru/pay/success",
            },
            "description": "Test payment",
        },
    )
    print(f"  HTTP {code}")
    if isinstance(data, dict):
        print(f"  id:     {data.get('id')}")
        print(f"  status: {data.get('status')}")
        print(f"  test:   {data.get('test')}")
        conf = data.get("confirmation") or {}
        print(f"  url:    {conf.get('confirmation_url')}")
    else:
        print(f"  {data}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
