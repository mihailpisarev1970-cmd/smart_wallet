"""Тесты конвертации аудио в WAV (критично для STT).

AI Dostup принимает в ``/audio/transcriptions`` только WAV/PCM: OGG/Opus из
MAX, а также MP3, M4A и FLAC дают HTTP 400. Без конвертации голосовой ввод
не работает вовсе (проверено ``scripts/test_stt_convert.py``).
"""

from __future__ import annotations

import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from bot.utils.audio import (
    TARGET_SAMPLE_RATE,
    ffmpeg_available,
    looks_like_wav,
    to_wav,
)


def make_ogg_with_ffmpeg(seconds: float = 1.0) -> bytes | None:
    """Сгенерировать OGG/Opus через ffmpeg (как присылает MAX)."""
    if not shutil.which("ffmpeg"):
        return None

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "voice.ogg"
        command = [
            shutil.which("ffmpeg") or "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:a",
            "libopus",
            str(out),
        ]
        try:
            subprocess.run(command, capture_output=True, timeout=60, check=False)
        except Exception:
            return None
        return out.read_bytes() if out.exists() else None


def make_wav() -> bytes:
    """Простой WAV с сигнатурой RIFF....WAVE."""
    data = b"\x00\x00" * 1000
    header = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
    header += b"data" + struct.pack("<I", len(data))
    return header + data


def test_looks_like_wav_true() -> None:
    assert looks_like_wav(make_wav())


@pytest.mark.parametrize(
    "data",
    [
        b"OggS" + b"\x00" * 30,
        b"ID3" + b"\x00" * 30,
        b"\x00" * 4,
        b"",
        b"RIFF1234XXXX",  # RIFF, но не WAVE
    ],
)
def test_looks_like_wav_false(data: bytes) -> None:
    assert not looks_like_wav(data)


async def test_to_wav_keeps_existing_wav() -> None:
    """Готовый WAV не переконвертируется (без вызова ffmpeg)."""
    wav = make_wav()
    result = await to_wav(wav)
    assert result == wav


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg не установлен")
async def test_to_wav_converts_ogg_opus() -> None:
    """РЕГРЕССИЯ: OGG/Opus из MAX конвертируется в валидный WAV."""
    ogg = make_ogg_with_ffmpeg()
    if not ogg:
        pytest.skip("не удалось создать OGG через ffmpeg")

    assert not looks_like_wav(ogg), "исходный файл не должен быть WAV"

    wav = await to_wav(ogg)
    assert wav is not None, "конвертация не удалась"
    assert looks_like_wav(wav), "результат не WAV"
    assert len(wav) > len(ogg), "WAV/PCM должен быть больше сжатого OGG"


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg не установлен")
async def test_converted_wav_has_expected_sample_rate() -> None:
    """Частота дискретизации соответствует заданной (16 кГц)."""
    ogg = make_ogg_with_ffmpeg()
    if not ogg:
        pytest.skip("не удалось создать OGG через ffmpeg")

    wav = await to_wav(ogg, sample_rate=TARGET_SAMPLE_RATE)
    assert wav is not None

    # Разбираем fmt-чанк: sample rate на смещении 24 (little-endian).
    assert wav[12:16] == b"fmt "
    sample_rate = struct.unpack("<I", wav[24:28])[0]
    assert sample_rate == TARGET_SAMPLE_RATE


async def test_to_wav_returns_none_for_garbage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Мусорные байты → None (бот покажет ошибку, но не упадёт)."""
    if not ffmpeg_available():
        pytest.skip("ffmpeg не установлен")
    result = await to_wav(b"not an audio file at all")
    assert result is None


def test_ffmpeg_available_returns_bool() -> None:
    assert isinstance(ffmpeg_available(), bool)


# --- Повтор при сетевых ошибках STT ---------------------------------------


class StubSettings:
    """Минимальные настройки STT для теста."""

    stt_api_key = "test-key"
    stt_api_base_url = "https://example.com/v1"
    stt_primary_model = "gpt-4o-transcribe"
    stt_language = "ru"
    stt_timeout_seconds = 30.0
    stt_max_file_size_mb = 25


async def test_stt_retries_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """РЕГРЕССИЯ: таймаут провайдера не должен ронять распознавание.

    Реальный случай: AI Dostup ответил дольше таймаута, единственная
    рабочая модель упала, и пользователь получил ошибку. Повтор спасает.
    """
    import httpx

    import bot.services.stt_provider as stt_module

    monkeypatch.setattr(stt_module, "RETRY_DELAY_SECONDS", 0)

    transport = httpx.MockTransport(_flaky_handler(1))
    provider = stt_module.OpenAICompatibleSTT(StubSettings(), transport=transport)

    result = await provider.transcribe(make_wav(), "voice.wav")
    assert result.text == "Потратил 350 на кофе"
    assert result.model == "gpt-4o-transcribe"


def _flaky_handler(failures: int):
    """Обработчик MockTransport: N таймаутов, затем успешный ответ."""
    import httpx

    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] <= failures:
            raise httpx.ReadTimeout("timeout", request=request)
        return httpx.Response(200, json={"text": "Потратил 350 на кофе"}, request=request)

    return handler


async def test_stt_gives_up_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если провайдер всегда недоступен — понятная ошибка после всех попыток."""
    import httpx

    import bot.services.stt_provider as stt_module

    monkeypatch.setattr(stt_module, "RETRY_DELAY_SECONDS", 0)

    transport = httpx.MockTransport(_flaky_handler(99))
    provider = stt_module.OpenAICompatibleSTT(StubSettings(), transport=transport)

    with pytest.raises(stt_module.AIError):
        await provider.transcribe(make_wav(), "voice.wav")
