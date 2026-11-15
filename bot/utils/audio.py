"""Конвертация аудио в WAV через ffmpeg.

Зачем: AI Dostup принимает в ``/audio/transcriptions`` **только WAV (PCM)**.
MAX присылает голосовые в OGG/Opus, а MP3, M4A, FLAC и WebM тоже дают
HTTP 400 «Некорректный запрос». Проверено эмпирически
(``scripts/test_stt_convert.py``): WAV на 8/16/44.1 кГц → 200 и корректный
текст, остальные контейнеры → 400.

Модуль деградирует мягко: если ffmpeg недоступен, возвращает исходные байты,
и бот покажет понятную ошибку вместо падения.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: Частота, которую принимает провайдер (16 кГц — стандарт для речи).
TARGET_SAMPLE_RATE = 16000

#: Формат, который гарантированно работает.
TARGET_FORMAT = "wav"

#: Таймаут конвертации (голосовые короткие, 60 с с запасом).
CONVERT_TIMEOUT_SECONDS = 60


def ffmpeg_available() -> bool:
    """Установлен ли ffmpeg в системе."""
    return shutil.which("ffmpeg") is not None


def _convert_sync(audio: bytes, target_format: str, sample_rate: int | None) -> bytes | None:
    """Синхронная конвертация через ffmpeg (вызывается в отдельном потоке)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None

    with tempfile.TemporaryDirectory(prefix="wallet_stt_") as tmp:
        source = Path(tmp) / "input"
        target = Path(tmp) / f"output.{target_format}"
        source.write_bytes(audio)

        command = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-ac",
            "1",  # моно
        ]
        if sample_rate:
            command += ["-ar", str(sample_rate)]
        if target_format == "wav":
            command += ["-c:a", "pcm_s16le"]
        command.append(str(target))

        try:
            result = subprocess_run(command)
        except Exception:
            logger.warning("ffmpeg: ошибка запуска", exc_info=True)
            return None

        if result != 0 or not target.exists():
            logger.warning("ffmpeg вернул код %s — конвертация не удалась", result)
            return None
        data = target.read_bytes()
        return data or None


def subprocess_run(command: list[str]) -> int:
    """Запустить ffmpeg и вернуть код возврата."""
    import subprocess

    completed = subprocess.run(
        command, capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS, check=False
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[:300]
        logger.warning("ffmpeg stderr: %s", stderr)
    return completed.returncode


async def to_wav(audio: bytes, *, sample_rate: int = TARGET_SAMPLE_RATE) -> bytes | None:
    """Конвертировать любое аудио в WAV/PCM. ``None`` — не удалось."""
    # Уже WAV? Проверяем сигнатуру RIFF....WAVE — конвертация не нужна.
    if len(audio) > 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE":
        return audio
    return await asyncio.to_thread(_convert_sync, audio, TARGET_FORMAT, sample_rate)


def looks_like_wav(audio: bytes) -> bool:
    """Проверить, что это WAV (сигнатура RIFF....WAVE)."""
    return len(audio) > 12 and audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"
