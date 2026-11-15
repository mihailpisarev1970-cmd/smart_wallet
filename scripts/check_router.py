"""Самопроверка маршрутизации и импорта всех модулей бота.

Запуск::

    python -m scripts.check_router

Отчёт пишется в ``.report/router.txt`` — так его удобно читать даже при
«шумном» терминале, и он сохраняется между запусками.
"""

from __future__ import annotations

import io
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

REPORT = PROJECT_ROOT / ".report" / "router.txt"


def main() -> int:
    REPORT.parent.mkdir(exist_ok=True)
    out = io.StringIO()
    try:
        import bot.handlers  # noqa: F401 - регистрирует обработчики
        from bot.router import router

        out.write("IMPORT: OK\n")
        out.write(f"callback-обработчиков: {len(router._callbacks)}\n")
        out.write(f"callback-префиксов:    {len(router._callbacks_prefix)}\n")
        out.write(f"команд:                {sorted(router._commands)}\n")
        out.write(f"событий:               {sorted(router._events)}\n")
        out.write(f"текстовый обработчик:  {getattr(router._text_handler, '__name__', None)}\n")
        out.write(f"голосовой обработчик:  {getattr(router._voice_handler, '__name__', None)}\n")
        out.write(f"fallback:              {getattr(router._fallback, '__name__', None)}\n\n")
        out.write("Действия кнопок:\n")
        for action in sorted(router._callbacks):
            handler = router._callbacks[action]
            out.write(f"  {action:26} -> {handler.__module__}.{handler.__name__}\n")
        code = 0
    except Exception:
        out.write("IMPORT: FAIL\n")
        out.write(traceback.format_exc())
        code = 1

    REPORT.write_text(out.getvalue(), encoding="utf-8")
    print(out.getvalue())
    return code


if __name__ == "__main__":
    sys.exit(main())
