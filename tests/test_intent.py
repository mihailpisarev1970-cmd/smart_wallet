"""Тесты определения намерения: операция или вопрос.

Реальный баг (14.11.2026): голосовое «Скажи пожалуйста, какие у меня
расходы в этом месяце?» распознавалось, уходило в парсер операций и
падало с «Не удалось распознать операцию».
"""

from __future__ import annotations

import pytest

from bot.services.intent import (
    classify_with_llm,
    detect_intent,
    looks_like_operation,
    looks_like_question,
)

# --- явные вопросы --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Скажи пожалуйста, какие у меня расходы в этом месяце?",
        "Сколько я потратил на продукты?",
        "на что я больше всего трачу",
        "Как сэкономить на еде?",
        "Расскажи про мой бюджет",
        "Покажи статистику за месяц",
        "Хватит ли мне денег до конца месяца?",
        "Какая самая затратная категория?",
        "Где я переплачиваю?",
        "Почему расходы выросли?",
        "Подскажи, как копить быстрее",
        "Сколько денег осталось?",
        "What are my expenses?",
        "How much did I spend?",
    ],
)
def test_detects_questions(text: str) -> None:
    assert looks_like_question(text) is True
    assert detect_intent(text) == "question"


# --- явные операции ------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Потратил 1250 на продукты",
        "Купил кофе за 320 рублей",
        "Заплатил 5000 за квартиру",
        "Получил зарплату 85000",
        "Такси 450",
        "Заработал 15000 на подработке",
        "Потратила 100 рублей на метро",
        "Купил хлеб 50",
    ],
)
def test_detects_operations(text: str) -> None:
    assert looks_like_question(text) is False
    assert looks_like_operation(text) is True
    assert detect_intent(text) == "operation"


# --- неоднозначные: решает LLM -------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "добавить что-нибудь",
        "ну не знаю",
        "интересно",
        "а если подумать",
    ],
)
def test_unclear_needs_llm(text: str) -> None:
    """Без суммы и без вопросительного слова — нужен LLM."""
    assert detect_intent(text) is None


def test_question_with_amount_is_question() -> None:
    """«Сколько я потратил 500 рублей на что?» — всё же вопрос."""
    assert looks_like_question("Сколько стоит 500 рублей в евро?") is True


def test_amount_with_operation_verb_detected() -> None:
    assert looks_like_operation("Потратил 1250 на продукты") is True
    # «1250 рублей» без сущности — тоже операция: категорию выберет пользователь.
    assert looks_like_operation("1250 рублей") is True
    # Без единиц и сущности — не операция (нужен LLM).
    assert looks_like_operation("привет как дела") is False


# --- LLM-классификация ----------------------------------------------------


class FakeProvider:
    """Провайдер, возвращающий заранее заданный ответ."""

    def __init__(self, content: str = "", error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.calls: list[dict] = []

    async def complete(self, messages, *, temperature=0.0, max_tokens=100):
        self.calls.append({"messages": messages, "max_tokens": max_tokens})

        class Result:
            pass

        if self.error is not None:
            raise self.error
        result = Result()
        result.content = self.content
        return result


async def test_llm_classifies_question() -> None:
    provider = FakeProvider("question")
    assert await classify_with_llm(provider, "а сколько у меня всего?") == "question"


async def test_llm_classifies_operation() -> None:
    provider = FakeProvider("operation")
    assert await classify_with_llm(provider, "хлеб 50") == "operation"


async def test_llm_defaults_to_operation_on_garbage() -> None:
    """Непонятный ответ модели — безопаснее считать операцией."""
    provider = FakeProvider("не знаю что-то")
    assert await classify_with_llm(provider, "хлеб 50") == "operation"


async def test_llm_defaults_to_operation_on_error() -> None:
    from bot.services.ai_base import AIError

    provider = FakeProvider(error=AIError("провайдер недоступен"))
    assert await classify_with_llm(provider, "какие расходы?") == "operation"


async def test_llm_uses_few_tokens() -> None:
    """Классификатор не должен тратить много токенов."""
    provider = FakeProvider("operation")
    await classify_with_llm(provider, "кофе 320")
    assert provider.calls[0]["max_tokens"] <= 16


async def test_llm_empty_text_unclear() -> None:
    provider = FakeProvider("question")
    assert await classify_with_llm(provider, "   ") == "unclear"
    assert provider.calls == []
