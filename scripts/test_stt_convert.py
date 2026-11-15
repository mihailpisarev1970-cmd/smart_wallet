"""Проверить STT после конвертации OGG/Opus → WAV через ffmpeg.

Гипотеза: AI Dostup принимает только WAV/PCM, а MAX присылает Opus.
Конвертируем сохранённый сэмпл и пробуем распознать.

Отчёт: ``.report/voice_convert.txt``.
"""

from __future__ import annotations

import asyncio
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import reload_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "voice_convert.txt"
SAMPLE = PROJECT_ROOT / ".report" / "voice_sample.bin"


def convert(src: bytes, target_format: str, sample_rate: int | None = None) -> bytes | None:
    """Конвертировать аудио через ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        src_path = Path(tmp) / "input.bin"
        dst_path = Path(tmp) / f"output.{target_format}"
        src_path.write_bytes(src)

        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src_path)]
        if sample_rate:
            cmd += ["-ar", str(sample_rate)]
        cmd += ["-ac", "1"]
        if target_format == "wav":
            cmd += ["-c:a", "pcm_s16le"]
        cmd.append(str(dst_path))

        result = subprocess.run(cmd, capture_output=True, timeout=120)
        if result.returncode != 0 or not dst_path.exists():
            return None
        return dst_path.read_bytes()


async def main() -> int:
    settings = reload_settings()
    out = io.StringIO()

    def log(message: str = "") -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    if not SAMPLE.exists():
        log(f"Нет сэмпла: {SAMPLE}")
        return 1

    original = SAMPLE.read_bytes()
    log(f"Исходник: {len(original)} байт, OGG/Opus")
    log(f"ffmpeg: {shutil.which('ffmpeg')}")

    base = settings.stt_api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}

    converts = [
        ("WAV 16kHz mono", "wav", 16000, "voice.wav", "audio/wav"),
        ("WAV 44.1kHz mono", "wav", 44100, "voice.wav", "audio/wav"),
        ("WAV 8kHz mono", "wav", 8000, "voice.wav", "audio/wav"),
        ("MP3", "mp3", None, "voice.mp3", "audio/mpeg"),
        ("M4A", "m4a", None, "voice.m4a", "audio/mp4"),
        ("FLAC", "flac", None, "voice.flac", "audio/flac"),
    ]

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0), verify=verify_option()) as client:
        for label, fmt, rate, filename, mime in converts:
            log(f"\n=== {label} ===")
            converted = convert(original, fmt, rate)
            if converted is None:
                log("  конвертация НЕ удалась")
                continue
            log(f"  размер: {len(converted)} байт")
            log(f"  первые байты: {converted[:16].hex()}")

            path = PROJECT_ROOT / ".report" / f"converted_{fmt}_{rate or 'def'}.bin"
            path.write_bytes(converted)

            try:
                stt = await client.post(
                    f"{base}/audio/transcriptions",
                    headers=headers,
                    data={"model": "gpt-4o-transcribe", "language": "ru"},
                    files={"file": (filename, converted, mime)},
                )
                log(f"  STT → HTTP {stt.status_code}")
                log(f"  ОТВЕТ: {stt.text[:400]}")
            except Exception as exc:
                log(f"  ИСКЛЮЧЕНИЕ: {type(exc).__name__}: {exc}")

    print(out.getvalue()[:6000])
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
