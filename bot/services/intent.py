"""Определение намерения: операция или вопрос AI-помощнику.

Проблема (найдена 14.11.2026): любой текст и голос уходили в парсер
операций. Пользователь спрашивал «какие у меня расходы в этом месяце?»
— парсер не находил суммы и отвечал «Не удалось распознать операцию».

Решение — двухступенчатое:

1. **Быстрая эвристика** (:func:`looks_like_question`): вопросительный знак,
   вопросительные слова в начале фразы. Дёшево, без вызова LLM.
2. **LLM-классификация** (:func:`classify_with_llm`): если эвристика не
   уверена, спрашиваем модель, что это — ``operation``, ``question`` или
   ``unclear``. Один короткий запрос с ``max_tokens`` ≈ 10.

Эвристика нужна, чтобы не тратить лишний AI-запрос на очевидные случаи:
«Потратил 1250 на продукты» — точно операция (цифры + глагол траты),
«Сколько я потратил?» — точно вопрос (вопросительное слово + знак).
"""

from __future__ import annotations

import logging
import re
from typing import Literal

from bot.services.ai_base import AIError, AINotConfiguredError
from bot.services.llm_provider import LLMProvider

logger = logging.getLogger(__name__)

#: Что означает текст пользователя.
Intent = Literal["operation", "question", "unclear"]

#: Вопросительные слова в начале фразы (в нижнем регистре).
_QUESTION_STARTS = (
    "сколько",
    "какие",
    "какой",
    "какая",
    "каких",
    "что",
    "чем",
    "где",
    "когда",
    "почему",
    "зачем",
    "как",
    "можно ли",
    "стоит ли",
    "хватит ли",
    "хватает ли",
    "на что",
    "куда",
    "кто",
    "чего",
    "расскажи",
    "покажи",
    "подскажи",
    "посчитай",
    "проанализируй",
    "сравни",
    "объясни",
    "помоги",
    "посоветуй",
    "что делать",
    "should i",
    "how much",
    "what",
    "how",
    "why",
    "where",
    "when",
)

#: Признаки описания траты/дохода (глаголы и предлоги трат).
_OPERATION_VERBS = (
    "потратил",
    "потратила",
    "потрачено",
    "потрачу",
    "купил",
    "купила",
    "купили",
    "приобрел",
    "приобрёл",
    "заплатил",
    "заплатила",
    "оплатил",
    "оплатила",
    "внес",
    "внёс",
    "внесла",
    "получил",
    "получила",
    "заработал",
    "заработала",
    "вернули",
    "продал",
    "продала",
    "перевел",
    "перевёл",
    "потратили",
    "ушел",
    "ушёл",
    "стоил",
    "стоило",
    "обошлось",
    "потратилось",
)

#: Регулярка на сумму: цифры (возможно с к/тыс/руб/₽).
_AMOUNT = re.compile(
    r"\d+([.,]\d+)?\s*(к\b|тыс|тысяч|руб|₽|р\.|рублей|доллар|\$|евро|€)?",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    """Эвристика: это скорее вопрос, чем описание операции?

    Возвращает ``True`` для явных вопросов, ``False`` для явных операций
    и для неоднозначных случаев (тогда решает LLM).
    """
    cleaned = " ".join((text or "").lower().split())
    if not cleaned:
        return False

    # Явный вопросительный знак — почти всегда вопрос.
    # ...кроме случаев «Купил хлеб? 50 рублей» — редко, но бывает.
    if "?" in cleaned and not _has_amount_with_operation(cleaned):
        return True

    # Вопросительное слово в начале фразы — вопрос.
    return any(cleaned.startswith(start) for start in _QUESTION_STARTS)


def looks_like_operation(text: str) -> bool:
    """Эвристика: это явное описание операции?

    Признаки операции:
    * глагол траты/дохода + сумма («потратил 1250 на продукты»);
    * короткая запись «сущность + сумма» без вопросительных слов
      («Такси 450», «Кофе 320», «Продукты 1500») — типичная манера
      вести учёт.
    """
    cleaned = " ".join((text or "").lower().split())
    if _has_amount_with_operation(cleaned):
        return True
    # «Такси 450» / «Кофе 320»: до 4 слов, есть сумма, нет вопросов.
    if _AMOUNT.search(cleaned) and not looks_like_question(cleaned):
        words = cleaned.split()
        if 1 <= len(words) <= 4:
            return True
    return False


def _has_amount_with_operation(cleaned: str) -> bool:
    """Есть ли и сумма, и глагол траты/дохода."""
    if not _AMOUNT.search(cleaned):
        return False
    return any(verb in cleaned for verb in _OPERATION_VERBS)


def detect_intent(text: str) -> Intent | None:
    """Быстрое определение без LLM. ``None`` — нужен запрос к модели."""
    if looks_like_question(text):
        return "question"
    if looks_like_operation(text):
        return "operation"
    return None


CLASSIFY_PROMPT = """Ты — классификатор сообщений в боте учёта личных финансов.

Определи, что хочет пользователь, и ответь ОДНИМ словом:
- operation — он описывает трату или доход (есть сумма и событие);
- question — он задаёт вопрос, просит совет, анализ или объяснение.

Примеры:
«Потратил 1250 на продукты» → operation
«Кофе 320» → operation
«Зарплата 85000 пришла» → operation
«Какие у меня расходы в этом месяце?» → question
«На что я больше всего трачу?» → question
«Как сэкономить на еде?» → question
«Расскажи про мой бюджет» → question

Отвечай только словом: operation или question. Никаких пояснений."""


async def classify_with_llm(provider: LLMProvider, text: str) -> Intent:
    """Спросить модель, что это — операция или вопрос.

    При любой ошибке провайдера возвращаем ``"operation"`` — так безопаснее:
    если не смогли классифицировать, лучше попробовать разобрать как
    операцию (пользователь увидит понятную подсказку), чем молча уйти
    в AI-помощник и списать лишний запрос.
    """
    safe_text = " ".join((text or "").split())[:600]
    if not safe_text:
        return "unclear"

    messages = [
        {"role": "system", "content": CLASSIFY_PROMPT},
        {"role": "user", "content": f"<<<СООБЩЕНИЕ>>>\n{safe_text}"},
    ]
    try:
        response = await provider.complete(messages, max_tokens=8, temperature=0.0)
    except (AIError, AINotConfiguredError) as exc:
        logger.info("Классификация не удалась (%s) — считаем операцией", exc)
        return "operation"

    answer = (response.content or "").strip().lower()
    if "question" in answer:
        return "question"
    if "operation" in answer:
        return "operation"
    logger.info("Классификатор вернул %r — считаем операцией", answer[:40])
    return "operation"
