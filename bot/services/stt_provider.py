"""STT-провайдер: gpt-4o-transcribe (единственная модель).

ТЗ п. 4: MAX присылает голосовые/аудио, бот скачивает файл и отправляет его
в OpenAI-совместимый ``/audio/transcriptions``.

Модель одна: провайдер AI Dostup принимает **только** ``gpt-4o-transcribe`` —
``whisper-1`` удалён и возвращает HTTP 400 «Некорректный запрос… имя модели»
(проверено 08.11.2026, см. ``.report/stt_models.txt``).

Провайдер абстрагирован (``STTProvider``) — модели устаревают 26.02.2027,
заменить провайдера нужно без переписывания бота (ТЗ п. 16).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import httpx

from bot.config import Settings
from bot.constants import STT_SUPPORTED_FORMATS
from bot.services.ai_base import AIError, AINotConfiguredError
from bot.utils.audio import looks_like_wav, to_wav

logger = logging.getLogger(__name__)

#: Минимальная длина осмысленного распознанного текста.
MIN_TEXT_LENGTH = 3

#: Сколько раз повторять запрос при сетевой ошибке (таймаут).
#: AI Dostup иногда отвечает дольше таймаута — вторая попытка спасает.
MAX_NETWORK_RETRIES = 2

#: Пауза перед повтором, сек (умножается на номер попытки).
RETRY_DELAY_SECONDS = 1.0


@dataclass(slots=True)
class TranscriptionResult:
    """Результат распознавания речи."""

    text: str
    model: str
    latency_ms: int
    audio_duration_seconds: Decimal | None = None
    fallback_used: bool = False
    attempts: list[str] | None = None


class STTProvider(Protocol):
    """Интерфейс провайдера распознавания речи."""

    name: str

    async def transcribe(
        self, audio: bytes, filename: str, *, prompt: str | None = None
    ) -> TranscriptionResult: ...


def is_valid_transcription(text: str) -> bool:
    """Достаточно ли качественный результат, чтобы принять его.

    ТЗ п. 4.2: непустой результат, длина > 2 символов, без явных артефактов.
    """
    cleaned = (text or "").strip()
    if len(cleaned) < MIN_TEXT_LENGTH:
        return False
    letters = sum(char.isalpha() for char in cleaned)
    if letters < 2:
        return False
    # Признаки «мусора»: повторяющиеся символы/фразы, типичные галлюцинации Whisper.
    lowered = cleaned.lower().replace(" ", "")
    if len(set(lowered)) <= 2:
        return False
    for artifact in (
        "субтитры сделал",
        "продолжение следует",
        "спасибо за просмотр",
        "dimatorzok",
    ):
        if artifact in lowered:
            return False
    return True


def _mime_for(filename: str) -> str:
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "ogg"
    return {
        "ogg": "audio/ogg",
        "oga": "audio/ogg",
        "opus": "audio/ogg",
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "wav": "audio/wav",
        "webm": "audio/webm",
        "flac": "audio/flac",
        "mpeg": "audio/mpeg",
        "mpga": "audio/mpeg",
    }.get(suffix, "application/octet-stream")


def _extension_from_url(url: str | None) -> str:
    if url:
        clean = url.split("?")[0]
        if "." in clean:
            suffix = clean.rsplit(".", 1)[-1].lower()
            if suffix in STT_SUPPORTED_FORMATS:
                return suffix
    return "ogg"


class OpenAICompatibleSTT:
    """STT через OpenAI-совместимый ``/audio/transcriptions``.

    Один экземпляр работает с единственной моделью ``STT_PRIMARY_MODEL``
    (по умолчанию ``gpt-4o-transcribe``).
    """

    name = "openai_compatible"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport
        #: AI Dostup отклоняет ``prompt`` с кириллицей (тратя ~15 с на отказ).
        #: После первого отказа больше не отправляем — экономия времени.
        self._send_prompt = True

    def _client(self) -> httpx.AsyncClient:
        from bot.utils.tls import verify_option

        return httpx.AsyncClient(
            base_url=self._settings.stt_api_base_url,
            timeout=httpx.Timeout(self._settings.stt_timeout_seconds, connect=15.0),
            headers={"Authorization": f"Bearer {self._settings.stt_api_key}"},
            verify=verify_option(),
            transport=self._transport,
        )

    async def _transcribe_with(
        self, model: str, audio: bytes, filename: str, prompt: str | None
    ) -> tuple[str, int]:
        """Распознать файл одной моделью.

        Особенность AI Dostup (проверено эмпирически, ТЗ п. 4.4): параметр
        ``prompt`` с кириллицей приводит к HTTP 400, причём **после**
        длительной обработки (~15 секунд). Поэтому ``prompt`` по умолчанию
        не отправляется: экономия времени важнее — провайдер отдаёт
        корректный текст и без подсказки.
        """
        base_data: dict[str, str] = {
            "model": model,
            "language": self._settings.stt_language,
            "response_format": "json",
        }
        if prompt and self._send_prompt:
            base_data["prompt"] = prompt[:1000]

        started = time.perf_counter()
        try:
            async with self._client() as client:
                response = await client.post(
                    "/audio/transcriptions",
                    data=base_data,
                    files={"file": (filename, audio, _mime_for(filename))},
                )
                # Если prompt всё-таки был и его отклонили — повторяем без него.
                if response.status_code == 400 and "prompt" in base_data:
                    logger.info("STT: провайдер отклонил prompt, повторяем без подсказки")
                    retry_data = {k: v for k, v in base_data.items() if k != "prompt"}
                    # Запоминаем, что prompt больше не нужен (экономия 15 с на запрос).
                    self._send_prompt = False
                    response = await client.post(
                        "/audio/transcriptions",
                        data=retry_data,
                        files={"file": (filename, audio, _mime_for(filename))},
                    )
        except httpx.HTTPError as exc:
            raise AIError(f"STT: сетевая ошибка ({exc.__class__.__name__})") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if response.status_code == 401:
            raise AINotConfiguredError("STT: неверный ключ (401).")
        if response.status_code >= 400:
            raise AIError(f"STT {model}: HTTP {response.status_code} — {response.text[:200]}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIError(f"STT {model}: некорректный ответ") from exc
        text = str(payload.get("text") or "").strip()
        return text, latency_ms

    async def transcribe(
        self,
        audio: bytes,
        filename: str,
        *,
        prompt: str | None = None,
    ) -> TranscriptionResult:
        """Распознать аудио единственной моделью ``gpt-4o-transcribe``.

        Модель одна: AI Dostup принимает только её (``whisper-1`` удалён,
        HTTP 400). Поэтому нет перебора моделей, но есть повтор при сетевой
        ошибке — таймауты провайдера случаются (``MAX_NETWORK_RETRIES``).

        Перед отправкой аудио приводится к **WAV/PCM**: AI Dostup принимает
        только этот формат, а MAX присылает OGG/Opus (проверено:
        ``scripts/test_stt_convert.py``). Если ffmpeg недоступен — пробуем
        отправить как есть.
        """
        if not self._settings.stt_api_key:
            raise AINotConfiguredError("STT_API_KEY не задан — голосовой ввод недоступен.")
        if len(audio) > self._settings.stt_max_file_size_mb * 1024 * 1024:
            raise AIError(
                f"Файл больше {self._settings.stt_max_file_size_mb} МБ — распознавание невозможно."
            )

        # Приводим к формату, который принимает провайдер.
        wav = await to_wav(audio)
        if wav is not None:
            if not looks_like_wav(audio):
                logger.info(
                    "STT: аудио сконвертировано в WAV (%s → %s байт)",
                    len(audio),
                    len(wav),
                )
            audio = wav
            filename = "voice.wav"
        else:
            logger.warning(
                "STT: не удалось привести аудио к WAV (ffmpeg недоступен?) — "
                "провайдер может отклонить файл"
            )

        model = self._settings.stt_primary_model

        attempts: list[str] = []
        last_error: Exception | None = None
        # Сетевая ошибка (таймаут) — не приговор: провайдер может ответить
        # со второй попытки. Делаем до MAX_NETWORK_RETRIES попыток.
        for retry in range(1, MAX_NETWORK_RETRIES + 1):
            try:
                text, latency = await self._transcribe_with(model, audio, filename, prompt)
            except AINotConfiguredError as exc:
                attempts.append(f"{model}: {exc}")
                logger.warning("STT %s не удался: %s", model, exc)
                raise
            except AIError as exc:
                is_network = "сетевая ошибка" in str(exc) or "Таймаут" in str(exc)
                if is_network and retry < MAX_NETWORK_RETRIES:
                    logger.warning(
                        "STT %s: сетевая ошибка (попытка %s/%s), повторяю",
                        model,
                        retry,
                        MAX_NETWORK_RETRIES,
                    )
                    await asyncio.sleep(RETRY_DELAY_SECONDS * retry)
                    continue
                attempts.append(f"{model}: {exc}")
                last_error = exc
                logger.warning("STT %s не удался: %s", model, exc)
                break
            else:
                attempts.append(f"{model}: ok ({len(text)} симв.)")
                if is_valid_transcription(text):
                    return TranscriptionResult(
                        text=text,
                        model=model,
                        latency_ms=latency,
                        fallback_used=False,
                        attempts=attempts,
                    )
                logger.warning("STT %s вернул непригодный текст (%r)", model, text[:60])
                last_error = AIError(f"STT {model}: результат непригоден")
                break

        raise last_error or AIError("STT: распознавание не удалось")


def build_provider(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> STTProvider:
    """Собрать STT-провайдера по настройкам."""
    return OpenAICompatibleSTT(settings, transport=transport)

