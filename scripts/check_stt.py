"""Проверка STT на реальной русской речи.

Генерирует WAV с фразой через Windows SAPI (синтез речи), отправляет его
в STT-провайдер из ``.env`` и печатает распознанный текст.

Запуск::

    python -m scripts.check_stt
    python -m scripts.check_stt --file voice.ogg   # свой файл

Отчёт: ``.report/stt.txt``.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.services.ai_base import AIError, AINotConfiguredError  # noqa: E402
from bot.services.stt_provider import build_provider  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "stt.txt"
DEFAULT_PHRASE = "Потратил тысяча двести пятьдесят рублей на продукты"


def synthesize_speech(phrase: str, target: Path) -> bool:
    """Озвучить фразу через Windows SAPI (русский голос, если установлен)."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$ru = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'ru*' }; "
        "if ($ru) { $s.SelectVoice($ru[0].VoiceInfo.Name) }; "
        f"$s.SetOutputToWaveFile('{target}'); "
        f"$s.Speak('{phrase}'); "
        "$s.Dispose()"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        print(f"SAPI ошибка: {result.stderr[:300]}")
    return target.exists() and target.stat().st_size > 1000


async def main(file_path: str | None, phrase: str) -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    log(f"STT base: {settings.stt_api_base_url}")
    log(f"Модель:   {settings.stt_primary_model}")
    log(f"Настроен: {settings.stt_configured}")

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if file_path:
        audio_path = Path(file_path)
        if not audio_path.exists():
            log(f"ОШИБКА: файл не найден: {audio_path}")
            return 2
    else:
        temp_dir = tempfile.TemporaryDirectory()
        audio_path = Path(temp_dir.name) / "probe.wav"
        log(f"Синтез речи: {phrase!r}")
        if not synthesize_speech(phrase, audio_path):
            log("ОШИБКА: не удалось синтезировать речь (SAPI)")
            return 2

    audio = audio_path.read_bytes()
    log(f"Аудио: {audio_path.name}, {len(audio)} байт")

    provider = build_provider(settings)
    try:
        result = await provider.transcribe(
            audio,
            audio_path.name,
            prompt="Личные финансы: расходы, доходы, суммы в рублях, категории покупок.",
        )
    except AINotConfiguredError as exc:
        log(f"ОШИБКА конфигурации: {exc}")
        return 3
    except AIError as exc:
        log(f"ОШИБКА распознавания: {exc}")
        return 1
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()

    log(f"Распознано: {result.text!r}")
    log(f"Модель: {result.model}, fallback={result.fallback_used}, задержка={result.latency_ms} мс")
    log(f"Попытки: {result.attempts}")

    if result.text:
        log("")
        log("Разбор распознанного текста через LLM...")
        from bot.constants import DEFAULT_EXPENSE_CATEGORIES, DEFAULT_INCOME_CATEGORIES
        from bot.services.ai_schema import parse_operations
        from bot.services.llm_provider import build_provider as build_llm

        try:
            parsed = await parse_operations(
                build_llm(settings),
                result.text,
                expense_categories=list(DEFAULT_EXPENSE_CATEGORIES),
                income_categories=list(DEFAULT_INCOME_CATEGORIES),
            )
            for operation in parsed.operations:
                log(
                    f"  {operation.type} {operation.amount} {operation.currency} "
                    f"«{operation.category}» {operation.operation_date}"
                )
        except Exception as exc:
            log(f"  ошибка разбора: {type(exc).__name__}: {exc}")

    log("")
    log("OK: STT работает" if result.text else "ВНИМАНИЕ: распознан пустой текст")
    print(out.getvalue())
    return 0 if result.text else 4


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=str, default=None)
    parser.add_argument("--phrase", type=str, default=DEFAULT_PHRASE)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.file, args.phrase)))
