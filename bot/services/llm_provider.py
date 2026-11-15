"""LLM-провайдер: DeepSeek через AI Dostup (OpenAI-совместимый API).

ТЗ п. 5.2: ``POST {AI_DOSTUP_BASE_URL}/chat/completions``,
заголовок ``Authorization: Bearer <ключ>``, модель ``deepseek-v4.1-flash-1017``.

Провайдер абстрагирован (``LLMProvider``), чтобы его можно было заменить без
переписывания бота (ТЗ п. 16, 8-й принцип разработки).

Модуль занимается только транспортом и разбором JSON: решение о сохранении
операции принимает Python-код после валидации (:mod:`bot.services.ai_parser`).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from bot.config import Settings
from bot.services.ai_base import AIError, AINotConfiguredError

logger = logging.getLogger(__name__)

#: Сколько токенов разрешаем в ответе.
MAX_RESPONSE_TOKENS = 800


@dataclass(slots=True)
class LLMResult:
    """Ответ модели: текст, токены, задержка."""

    content: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> Any:
        """Извлечь JSON из ответа модели (в том числе из ```json-блока)."""
        return extract_json(self.content)


class LLMProvider(Protocol):
    """Интерфейс провайдера LLM (для замены без переписывания бота)."""

    name: str

    async def complete(
        self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int = MAX_RESPONSE_TOKENS
    ) -> LLMResult: ...


def extract_json(text: str) -> Any:
    """Достать JSON из ответа модели.

    Модель может обернуть объект в ```json ... ```, добавить пояснение или
    вернуть массив. Возвращает ``dict``/``list`` либо ``None``.
    """
    if not text:
        return None
    cleaned = text.strip()

    fenced = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()

    for candidate in (cleaned, cleaned[cleaned.find("{") : cleaned.rfind("}") + 1] if "{" in cleaned else "", cleaned[cleaned.find("[") : cleaned.rfind("]") + 1] if "[" in cleaned else ""):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


class AIDostupProvider:
    """DeepSeek через AI Dostup (реализация :class:`LLMProvider`)."""

    name = "ai_dostup"

    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._settings = settings
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        from bot.utils.tls import verify_option

        return httpx.AsyncClient(
            base_url=self._settings.ai_dostup_base_url,
            timeout=httpx.Timeout(self._settings.ai_timeout_seconds, connect=15.0),
            headers={
                "Authorization": f"Bearer {self._settings.ai_dostup_api_key}",
                "Content-Type": "application/json",
            },
            verify=verify_option(),
            transport=self._transport,
        )

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = MAX_RESPONSE_TOKENS,
    ) -> LLMResult:
        if not self._settings.ai_dostup_api_key:
            raise AINotConfiguredError(
                "AI_DOSTUP_API_KEY не задан — AI-функции недоступны."
            )

        payload = {
            "model": self._settings.ai_dostup_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        started = time.perf_counter()
        try:
            async with self._client() as client:
                response = await client.post("/chat/completions", json=payload)
        except httpx.HTTPError as exc:
            raise AIError(f"LLM: сетевая ошибка ({exc.__class__.__name__})") from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 401:
            raise AINotConfiguredError("LLM: неверный ключ AI Dostup (401).")
        if response.status_code >= 400:
            raise AIError(f"LLM: HTTP {response.status_code} — {response.text[:300]}")

        try:
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
        except (ValueError, AttributeError) as exc:
            raise AIError("LLM: некорректный ответ сервера") from exc

        usage = data.get("usage") or {}
        return LLMResult(
            content=content,
            model=str(data.get("model") or self._settings.ai_dostup_model),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_ms=latency_ms,
            raw=data,
        )


def build_provider(settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None) -> LLMProvider:
    """Собрать провайдера LLM по настройкам (сейчас — AI Dostup)."""
    return AIDostupProvider(settings, transport=transport)
