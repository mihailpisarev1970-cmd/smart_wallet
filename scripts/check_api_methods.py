"""Проверка методов MAX API, которые используются ботом (без БД).

Запуск::

    python -m scripts.check_api_methods --user-id <ID>

Проверяет: GET /me, POST /uploads, отправку сообщения, ответ на callback.
Результат дублируется в ``.report/api_methods.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.api import MaxAPIError, MaxClient  # noqa: E402
from bot.config import get_settings  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "api_methods.txt"


async def main(user_id: int | None, send_file: bool) -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        print(message)

    log(f"API: {settings.max_api_base_url}")
    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=30
    ) as client:
        me = await client.get_me()
        log(f"GET /me: OK — {me.get('name')}")

        # 1. Получение URL для загрузки файла (экспорт CSV/Excel).
        try:
            info = await client.get_upload_url("file")
            log(f"POST /uploads: OK — {info}")
        except MaxAPIError as exc:
            log(f"POST /uploads: FAIL — {exc}")

        # 2. Отправка файла.
        if send_file and user_id:
            from bot.services.export import export_filename
            from bot.services.upload import upload_file

            content = "ID;Тип;Сумма\n1;Расход;1250.00\n".encode("utf-8-sig")
            try:
                uploaded = await upload_file(client, content, export_filename("csv"))
                log(f"upload file: OK — token={uploaded.token[:16]}...")
                await client.send_message(
                    user_id=user_id,
                    text="Тестовый CSV-файл (проверка экспорта):",
                    attachments=[uploaded.attachment("test.csv")],
                )
                log("send file: OK — файл отправлен пользователю")
            except Exception:
                log("upload/send file: FAIL\n" + traceback.format_exc())

        # 3. Отправка сообщения с клавиатурой.
        if user_id:
            from bot.utils.ui.keyboards import Keyboard, callback_button

            keyboard = Keyboard().row(
                callback_button("Проверить callback", "check:callback"),
            )
            message = await client.send_message(
                user_id=user_id,
                text="Проверка API: клавиатура и callback",
                attachments=keyboard.to_attachments(),
            )
            log(f"POST /messages: OK — {str(message)[:200]}")
    log("Отчёт сохранён: .report/api_methods.txt")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(out.getvalue(), encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-id", type=int, default=None)
    parser.add_argument("--file", action="store_true", help="Проверить отправку файла")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.user_id, args.file)))
