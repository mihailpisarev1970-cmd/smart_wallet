"""Общие типы и логирование вызовов AI (ТЗ п. 4.2, 7.1).

Каждый вызов STT/LLM пишется в ``ai_usage_log``: модель, длительность аудио,
токены, успешность, стоимость и задержка.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from bot.db import Database

logger = logging.getLogger(__name__)

RequestType = Literal["stt", "parse", "multi", "assistant"]

#: Стоимость токенов DeepSeek ($ за 1M) — ТЗ п. 5.2.
LLM_INPUT_PRICE_USD = Decimal("0.30") / Decimal(1_000_000)
LLM_OUTPUT_PRICE_USD = Decimal("1.20") / Decimal(1_000_000)
#: Стоимость STT ~$0.006 за минуту (ТЗ п. 16).
STT_PRICE_PER_MINUTE_USD = Decimal("0.006")


class AIError(Exception):
    """Ошибка провайдера AI (сеть, таймаут, некорректный ответ)."""


class AINotConfiguredError(AIError):
    """Провайдер не настроен (нет ключа в .env)."""


@dataclass(slots=True)
class AIUsage:
    """Данные для записи в ``ai_usage_log``."""

    user_id: int | None
    request_type: RequestType
    provider: str
    model_used: str
    success: bool = True
    audio_duration_seconds: Decimal | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    error_message: str = ""
    fallback_used: bool = False
    cost_usd: Decimal | None = None


def estimate_llm_cost(prompt_tokens: int | None, completion_tokens: int | None) -> Decimal:
    """Оценка стоимости запроса LLM в долларах."""
    prompt_cost = LLM_INPUT_PRICE_USD * Decimal(prompt_tokens or 0)
    completion_cost = LLM_OUTPUT_PRICE_USD * Decimal(completion_tokens or 0)
    return (prompt_cost + completion_cost).quantize(Decimal("0.000001"))


def estimate_stt_cost(seconds: Decimal | float | None) -> Decimal:
    """Оценка стоимости распознавания речи."""
    if not seconds:
        return Decimal("0.000000")
    minutes = Decimal(str(seconds)) / Decimal(60)
    return (minutes * STT_PRICE_PER_MINUTE_USD).quantize(Decimal("0.000001"))


class AIUsageLogger:
    """Запись вызовов AI в БД."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def log(self, usage: AIUsage) -> None:
        tokens = None
        if usage.prompt_tokens is not None or usage.completion_tokens is not None:
            tokens = (usage.prompt_tokens or 0) + (usage.completion_tokens or 0)
        try:
            await self._db.execute(
                """
                INSERT INTO ai_usage_log (user_id, request_type, provider, model_used,
                                          audio_duration_seconds, tokens_used, prompt_tokens,
                                          completion_tokens, cost_usd, latency_ms, success,
                                          error_message, fallback_used, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW())
                """,
                usage.user_id,
                usage.request_type,
                usage.provider[:32],
                usage.model_used[:64],
                usage.audio_duration_seconds,
                tokens,
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.cost_usd,
                usage.latency_ms,
                usage.success,
                usage.error_message[:1000],
                usage.fallback_used,
            )
        except Exception as exc:
            logger.warning("Не удалось записать ai_usage_log: %s", exc)
