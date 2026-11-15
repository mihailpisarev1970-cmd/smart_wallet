"""Общие фикстуры тестов.

Тесты не требуют сети и БД: проверяются чистые функции (деньги, даты,
подписи, валидация ответов LLM, клавиатуры, роутер).
"""

from __future__ import annotations

import pytest

from bot.router import Router


@pytest.fixture()
def router() -> Router:
    """Чистый роутер без глобальных обработчиков."""
    return Router()
