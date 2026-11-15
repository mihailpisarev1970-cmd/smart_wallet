"""Ограничение частоты входящих запросов (ТЗ п. 11).

Простой token bucket в памяти процесса: защищает от флуда событиями MAX
и от многократных нажатий кнопок. Не является распределённым лимитом —
при нескольких воркерах счётчик у каждого свой, но для одного процесса
(как в проде) этого достаточно.

Использование::

    limiter = RateLimiter(per_second=5, burst=10)
    if not limiter.allow(user_id):
        # слишком часто — тихо игнорируем или отвечаем «не так быстро»
"""

from __future__ import annotations

import time
from collections import deque
from typing import Final

#: По умолчанию: 5 событий в секунду с запасом до 10 (нажатия кнопок пачкой).
DEFAULT_PER_SECOND: Final[int] = 5
DEFAULT_BURST: Final[int] = 10

#: Сколько секунд хранить историю для «молчащих» ключей.
_IDLE_TTL_SECONDS: Final[float] = 300.0


class RateLimiter:
    """Скользящее окно: не более ``per_second`` событий в секунду на ключ."""

    def __init__(self, per_second: int = DEFAULT_PER_SECOND, burst: int = DEFAULT_BURST) -> None:
        self._per_second = max(1, per_second)
        self._burst = max(self._per_second, burst)
        self._events: dict[int, deque[float]] = {}
        self._last_cleanup = time.monotonic()

    def allow(self, key: int) -> bool:
        """Пропустить событие? ``key`` — обычно ``max_user_id``."""
        now = time.monotonic()
        self._cleanup(now)

        window = self._events.get(key)
        if window is None:
            window = deque(maxlen=self._burst)
            self._events[key] = window

        # Отбрасываем всё, что старше секунды.
        while window and now - window[0] >= 1.0:
            window.popleft()

        if len(window) >= self._per_second:
            return False

        window.append(now)
        return True

    def _cleanup(self, now: float) -> None:
        """Периодически забывать неактивные ключи (утечка памяти)."""
        if now - self._last_cleanup < _IDLE_TTL_SECONDS:
            return
        self._last_cleanup = now
        stale = [
            key
            for key, window in self._events.items()
            if not window or now - window[-1] > _IDLE_TTL_SECONDS
        ]
        for key in stale:
            self._events.pop(key, None)

    @property
    def tracked_keys(self) -> int:
        """Сколько ключей в памяти (для диагностики)."""
        return len(self._events)
