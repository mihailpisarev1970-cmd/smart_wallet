"""Маршрутизация событий к обработчикам.

Простой явный роутер без внешних фреймворков:

* обработчик — ``async def handler(ctx) -> ScreenView | list[ScreenView] | None``;
* регистрация — ``@router.callback("tx:new")``, ``@router.command("/start")``;
* ``router.dispatch(ctx)`` выбирает первый подходящий обработчик.

Модули-сценарии (``bot.handlers.*``) импортируются в :mod:`bot.handlers`,
чтобы они зарегистрировали свои обработчики при старте.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from bot.context import Context
from bot.utils.ui.screen import ScreenView

logger = logging.getLogger(__name__)

Handler = Callable[[Context], Awaitable[ScreenView | list[ScreenView] | None]]


class Router:
    """Реестр обработчиков и их вызов по событию."""

    def __init__(self) -> None:
        self._callbacks: dict[str, Handler] = {}
        self._callbacks_prefix: list[tuple[str, Handler]] = []
        self._commands: dict[str, Handler] = {}
        self._commands_prefix: list[tuple[str, Handler]] = []
        self._events: dict[str, Handler] = {}
        self._text_handler: Handler | None = None
        self._voice_handler: Handler | None = None
        self._fallback: Handler | None = None

    # --- регистрация -----------------------------------------------------

    def callback(self, action: str, *, prefix: bool = False) -> Callable[[Handler], Handler]:
        """Обработчик нажатия кнопки с данным action (например ``tx:new``)."""

        def decorator(handler: Handler) -> Handler:
            if prefix:
                self._callbacks_prefix.append((action, handler))
            else:
                self._callbacks[action] = handler
            return handler

        return decorator

    def command(self, command: str, *, prefix: bool = False) -> Callable[[Handler], Handler]:
        """Обработчик текстовой команды (``/start``)."""

        def decorator(handler: Handler) -> Handler:
            key = command.lower()
            if prefix:
                self._commands_prefix.append((key, handler))
            else:
                self._commands[key] = handler
            return handler

        return decorator

    def event(self, update_type: str) -> Callable[[Handler], Handler]:
        """Обработчик системного события (``bot_started`` и т.п.)."""

        def decorator(handler: Handler) -> Handler:
            self._events[update_type] = handler
            return handler

        return decorator

    def text(self, handler: Handler) -> Handler:
        """Обработчик свободного текста (если нет команды и callback)."""
        self._text_handler = handler
        return handler

    def voice(self, handler: Handler) -> Handler:
        """Обработчик голосовых сообщений и аудиофайлов."""
        self._voice_handler = handler
        return handler

    def set_fallback(self, handler: Handler) -> None:
        """Обработчик по умолчанию, если ничего не подошло."""
        self._fallback = handler

    # --- выбор обработчика -----------------------------------------------

    def resolve(self, ctx: Context) -> Handler | None:
        if ctx.event == "callback":
            handler = self._callbacks.get(ctx.text)
            if handler:
                return handler
            for prefix, candidate in self._callbacks_prefix:
                if ctx.text.startswith(prefix):
                    return candidate
            return self._fallback

        if ctx.event == "command":
            command = ctx.text.split()[0].lower() if ctx.text else ""
            handler = self._commands.get(command)
            if handler:
                return handler
            for prefix, candidate in self._commands_prefix:
                if command.startswith(prefix):
                    return candidate
            return self._fallback

        if ctx.event in {"message", "voice"}:
            if ctx.event == "voice" and self._voice_handler is not None:
                return self._voice_handler
            return self._text_handler or self._fallback

        if ctx.event == "system":
            return self._events.get(ctx.text) or self._fallback

        return self._fallback

    async def dispatch(self, ctx: Context) -> list[ScreenView]:
        """Выполнить подходящий обработчик; вернуть экраны-ответы."""
        handler = self.resolve(ctx)
        if handler is None:
            logger.warning("Нет обработчика для %s/%r", ctx.event, ctx.text[:60])
            return []
        result = await handler(ctx)
        if result is None:
            return []
        if isinstance(result, ScreenView):
            return [result]
        return list(result)


#: Глобальный роутер, наполняемый модулями-сценариями.
router = Router()
