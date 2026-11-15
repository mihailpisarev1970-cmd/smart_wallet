"""Проверка: можно ли получить сообщение по mid и какие вложения бывают.

Ключевые вопросы:
1. Работает ли ``GET /messages?message_ids=`` (получить сообщение по mid)?
2. Какие типы вложений поддерживает API (audio / voice / file)?
3. Что отдаёт ``GET /messages/{mid}``?

Отчёт: ``.report/voice_diag3.txt``.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_diag3.txt"
CHAT_ID = 461841194
KNOWN_MID = "mid.000000001b87232a01a1ba48980e6e19"


async def main() -> int:
    settings = get_settings()
    base = settings.max_api_base_url.rstrip("/")
    headers = {"Authorization": settings.max_bot_token}
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(40.0), verify=verify_option(), headers=headers
    ) as client:
        log("=== 1. GET /messages?message_ids=<mid> ===")
        probes = [
            ("messages?message_ids", {"chat_id": CHAT_ID, "message_ids": KNOWN_MID}),
            ("messages (mid+count)", {"chat_id": CHAT_ID, "message_ids": KNOWN_MID, "count": 1}),
        ]
        for label, params in probes:
            try:
                response = await client.get(f"{base}/messages", params=params)
                log(f"  [{response.status_code}] {label} → {response.text[:300]}")
                if response.status_code < 400:
                    log("  ПОЛНАЯ СТРУКТУРА:")
                    log(json.dumps(response.json(), ensure_ascii=False, indent=2)[:1800])
            except Exception as exc:
                log(f"  [ERR ] {label}: {type(exc).__name__}: {exc}")

        log("\n=== 2. GET /messages/{mid} ===")
        try:
            response = await client.get(f"{base}/messages/{KNOWN_MID}")
            log(f"  [{response.status_code}] → {response.text[:400]}")
        except Exception as exc:
            log(f"  [ERR ] {type(exc).__name__}: {exc}")

        log("\n=== 3. Что известно про вложения (docs) ===")
        log("  Из .docs/update.one.txt структура audio:")
        log('  { "type": "audio", "payload": { "url": "...", "token": "...",')
        log('    "transcription": "...", "duration": 0 } }')

        log("\n=== 4. Проверка типов вложений в отправке ===")
        log("  (пропущено — не отправляем сообщения)")

    print(out.getvalue()[:5000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
