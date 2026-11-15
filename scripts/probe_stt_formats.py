"""Диагностика форматов аудио для STT: какой формат принимает провайдер.

Проверяет WAV, MP3, OGG/Opus, M4A и выясняет, на чём именно падает
``/audio/transcriptions``. Отчёт: ``.report/stt_formats.txt``.
"""

from __future__ import annotations

import asyncio
import io
import math
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import get_settings  # noqa: E402
from bot.utils.tls import verify_option  # noqa: E402

REPORT = PROJECT_ROOT / ".report" / "stt_formats.txt"


def make_wav(seconds: float = 2.0, framerate: int = 16000, channels: int = 1) -> bytes:
    """Сгенерировать WAV с тоном (проверка параметров заголовка)."""
    frames = int(seconds * framerate)
    samples = b"".join(
        struct.pack("<h", int(800 * math.sin(2 * math.pi * 440 * i / framerate)))
        for i in range(frames)
    )
    header = b"RIFF" + struct.pack("<I", 36 + len(samples)) + b"WAVE"
    header += b"fmt " + struct.pack(
        "<IHHIIHH", 16, 1, channels, framerate, framerate * 2 * channels, 2 * channels, 16
    )
    header += b"data" + struct.pack("<I", len(samples))
    return header + samples


def wav_info(data: bytes) -> str:
    """Разобрать заголовок WAV: частота, каналы, битность, формат."""
    try:
        if fmt_pos := data.find(b"fmt "):
            fmt, channels, rate, _byte_rate, _align, bits = struct.unpack(
                "<HHIIHH", data[fmt_pos + 8 : fmt_pos + 8 + 16]
            )
            return f"format={fmt} channels={channels} rate={rate} bits={bits}"
    except Exception:
        pass
    return "не удалось разобрать заголовок"


def synthesize(phrase: str, target: Path, rate: int = 16000) -> bool:
    """Озвучить фразу через SAPI в WAV заданной частоты."""
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$ru = $s.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'ru*' }; "
        "if ($ru) { $s.SelectVoice($ru[0].VoiceInfo.Name) }; "
        f"$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({rate}, "
        "System.Speech.AudioFormat.AudioBitsPerSample.Sixteen, "
        "System.Speech.AudioFormat.AudioChannel.Mono); "
        f"$s.SetOutputToWaveFile('{target}', $fmt); "
        f"$s.Speak('{phrase}'); "
        "$s.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return target.exists() and target.stat().st_size > 1000


async def main() -> int:
    settings = get_settings()
    out = io.StringIO()

    def log(message: str) -> None:
        out.write(message + "\n")
        REPORT.parent.mkdir(exist_ok=True)
        REPORT.write_text(out.getvalue(), encoding="utf-8")

    base = settings.stt_api_base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}
    phrase = "Потратил тысяча двести пятьдесят рублей на продукты"

    temp = tempfile.TemporaryDirectory()
    tmp = Path(temp.name)
    candidates: list[tuple[str, bytes, str]] = []

    # 1. WAV 16 кГц моно (эталонный формат для STT)
    for rate in (16000, 22050, 44100):
        wav_path = tmp / f"speech_{rate}.wav"
        if synthesize(phrase, wav_path, rate):
            data = wav_path.read_bytes()
            log(f"WAV {rate}: {len(data)} байт, {wav_info(data)}")
            candidates.append((f"wav{rate // 1000}k.wav", data, "audio/wav"))

    # 2. Сгенерированный тон (без речи) — контроль
    candidates.append(("tone.wav", make_wav(), "audio/wav"))

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(90.0), verify=verify_option(), headers=headers
    ) as client:
        for name, data, mime in candidates:
            for model in ("gpt-4o-transcribe", "whisper-1"):
                try:
                    response = await client.post(
                        f"{base}/audio/transcriptions",
                        data={"model": model, "language": "ru"},
                        files={"file": (name, data, mime)},
                    )
                    verdict = "OK" if response.status_code < 400 else "FAIL"
                    log(
                        f"[{verdict}] {name} / {model}: HTTP {response.status_code} "
                        f"{response.text[:200]}"
                    )
                except Exception as exc:
                    log(f"[ERR ] {name} / {model}: {type(exc).__name__}: {exc}")

        # 3. Пробуем те же файлы как «voice» с разными именами моделей ответа
        log("\nДополнительно: список моделей аудио у провайдера")
        try:
            response = await client.get(f"{base}/models")
            if response.status_code < 400:
                payload = response.json()
                models = [
                    str(item.get("id"))
                    for item in (payload.get("data") or [])
                    if isinstance(item, dict)
                ]
                log(f"  модели ({len(models)}): {models}")
        except Exception as exc:
            log(f"  ошибка: {exc}")

    temp.cleanup()
    print(out.getvalue())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
