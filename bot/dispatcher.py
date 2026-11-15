"""Диспетчер событий: собирает контекст, вызывает роутер и отправляет ответы.

Порядок обработки одного события:

1. Идемпотентность — повторно доставленное событие пропускается.
2. ``bot_started`` / сообщения: находим или создаём пользователя в БД.
3. Собираем :class:`bot.context.Context` (пользователь, состояние, зависимости).
4. Роутер выбирает обработчик и возвращает список экранов.
5. Отправляем экраны в MAX (лимит MAX — не более 2 сообщений/сек на диалог).
6. Сохраняем новое состояние диалога в БД.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from bot.api import MaxAPIError, MaxClient
from bot.config import Settings, get_settings
from bot.context import Context
from bot.db import Database
from bot.db.idempotency import IdempotencyGuard, build_update_id
from bot.db.states import StateRepository
from bot.db.users import CategoryRepository, UserRepository
from bot.router import router
from bot.update_parser import (
    IGNORED_EVENTS,
    MESSAGE_EVENTS,
    extract_attachments,
    extract_chat_id,
    extract_message_id,
    extract_sender,
    extract_text,
    find_voice_attachment,
    parse_payload,
)
from bot.utils.ui.menu import main_menu_screen
from bot.utils.ui.screen import ScreenView

logger = logging.getLogger(__name__)

#: Пауза между сообщениями в один диалог (лимит MAX — 2 сообщения в секунду).
MESSAGE_DELAY_SECONDS = 0.6

#: Системные события, которые обрабатываются роутером.
SYSTEM_EVENTS = {"bot_started", "bot_stopped", "dialog_removed"}

#: Сколько раз пробовать восстановить сообщение (MAX отдаёт событие раньше,
#: чем сообщение появляется в ``GET /messages`` — особенно для голосовых).
RESTORE_ATTEMPTS = 4

#: Пауза между попытками восстановления, сек.
RESTORE_DELAY_SECONDS = 0.7

#: Допустимая разница во времени между событием и сообщением (мс).
RESTORE_WINDOW_MS = 15_000

#: Сколько обработанных ``mid`` помнить, чтобы не восстановить их повторно.
SEEN_MIDS_LIMIT = 200


@dataclass
class Dispatcher:
    """Обработчик событий MAX."""

    db: Database
    api: MaxClient
    settings: Settings

    def __post_init__(self) -> None:
        self.users = UserRepository(self.db)
        self.categories = CategoryRepository(self.db)
        self.states = StateRepository(self.db)
        self.guard = IdempotencyGuard(self.db)
        #: Известные chat_id диалогов — нужны для восстановления голосовых
        #: сообщений (MAX присылает их без поля ``message``).
        self._known_chats: list[int] = []
        #: Уже обработанные ``mid`` — защита от повторного восстановления.
        self._seen_mids: list[str] = []

    # --- публичный интерфейс ---------------------------------------------

    async def handle_update(self, update: dict[str, Any]) -> None:
        """Обработать одно событие MAX (из long polling или webhook)."""
        update_type = str(update.get("update_type") or "")
        if update_type in IGNORED_EVENTS:
            logger.debug("Событие %s игнорируется", update_type)
            return

        # MAX присылает голосовые как message_created БЕЗ поля `message`
        # (проверено: scripts/diag_updates.py). Восстанавливаем сообщение.
        update = await self._restore_message(update, update_type)

        # Кто совершил действие — зависит от типа события:
        # * message_created / message_edited → message.sender;
        # * message_callback → callback.user (message.sender здесь — сам бот!);
        # * bot_started / bot_stopped → user.
        actor = self._extract_actor(update, update_type)
        if not actor or actor.get("is_bot"):
            logger.debug("Событие %s без пользователя-актора — пропуск", update_type)
            return

        sender_user_id = actor.get("user_id")
        if not sender_user_id:
            logger.warning("Событие %s без user_id", update_type)
            return

        update_id = build_update_id(update)
        if not await self.guard.is_new(update_id, update_type, int(sender_user_id)):
            logger.info("Повторное событие %s — пропускаем", update_id)
            return

        # Сообщение обработано — запоминаем mid, чтобы восстановитель не
        # вернул его повторно на следующее событие без `message`.
        self.remember_message_id(extract_message_id(update))

        logger.debug("Событие %s от %s", update_type, sender_user_id)
        try:
            await self._dispatch(update, update_type, actor, sender_user_id)
        except Exception:
            logger.exception("Ошибка обработки события %s", update_id)

    async def _restore_message(
        self, update: dict[str, Any], update_type: str
    ) -> dict[str, Any]:
        """Восстановить сообщение, если событие пришло без поля ``message``.

        Особенность MAX: голосовые сообщения доставляются как
        ``message_created`` **только** с ``timestamp``, ``update_type`` и
        ``user_locale`` — без ``message``, без ``chat_id`` и без ``user_id``.

        Поэтому:
        1. пробуем ``GET /messages/{mid}``, если событие принесло ``mid``;
        2. иначе опрашиваем ``GET /messages?chat_id=`` по всем известным чатам
           **с несколькими попытками** — сообщение может появиться в истории
           с задержкой после события;
        3. отбрасываем сообщения, которые уже обработаны (``mid`` не должен
           повторить предыдущее событие — иначе голосовое «превращалось» в
           старый ``/start``);
        4. выбираем **самое свежее** подходящее сообщение, а не первое
           попавшееся, и требуем близость по времени (±15 сек).
        """
        if update_type not in MESSAGE_EVENTS or update.get("message"):
            return update

        event_ts = int(update.get("timestamp") or 0)

        # chat_id может прийти в событии (в webhook-режиме) — тогда порядок важен.
        candidates: list[int] = list(self._known_chats)
        event_chat = update.get("chat_id")
        if event_chat:
            try:
                event_chat_int = int(event_chat)
            except (TypeError, ValueError):
                event_chat_int = 0
            if event_chat_int:
                if event_chat_int in candidates:
                    candidates.remove(event_chat_int)
                candidates.insert(0, event_chat_int)

        # Дополняем список чатами недавно активных пользователей из БД:
        # событие без chat_id иначе можно «привязать» не к тому диалогу.
        try:
            recent = await self.users.recent_chat_ids(limit=10)
        except Exception:
            logger.debug("Не удалось получить последние чаты из БД", exc_info=True)
            recent = []
        for chat_id in recent:
            if chat_id not in candidates:
                candidates.append(chat_id)

        logger.info(
            "Событие %s без message (ts=%s) — восстанавливаю через GET /messages "
            "по чатам %s",
            update_type,
            event_ts,
            candidates,
        )

        # Несколько попыток: MAX отдаёт событие раньше, чем сообщение
        # появляется в истории (актуально для голосовых).
        for attempt in range(1, RESTORE_ATTEMPTS + 1):
            best: tuple[int, int, dict[str, Any], int] | None = None

            for chat_id in candidates:
                try:
                    payload = await self.api.get_messages(chat_id, count=15)
                except MaxAPIError as exc:
                    logger.warning("GET /messages chat_id=%s: %s", chat_id, exc)
                    continue

                for message in payload.get("messages") or []:
                    if not isinstance(message, dict):
                        continue
                    sender = message.get("sender") or {}
                    if sender.get("is_bot"):
                        continue
                    body = message.get("body") or {}
                    mid = body.get("mid") or message.get("mid")
                    if mid and mid in self._seen_mids:
                        continue  # уже обработали — это старое сообщение
                    message_ts = int(message.get("timestamp") or 0)
                    # Событие и сообщение должны быть рядом по времени.
                    if event_ts and message_ts:
                        delta = abs(event_ts - message_ts)
                        if delta > RESTORE_WINDOW_MS:
                            continue
                    else:
                        delta = 0
                    if not body.get("attachments") and not body.get("text"):
                        continue

                    # Самое свежее (минимальная разница по времени) побеждает.
                    if best is None or delta < best[0]:
                        best = (delta, chat_id, message, message_ts)

            if best is not None:
                _delta, chat_id, message, _message_ts = best
                body = message.get("body") or {}
                attachments = body.get("attachments") or []
                mid = body.get("mid") or message.get("mid")
                logger.info(
                    "Восстановлено сообщение mid=%s (попытка %s): вложения=%s, "
                    "текст=%r, sender=%s",
                    mid,
                    attempt,
                    [item.get("type") for item in attachments if isinstance(item, dict)],
                    (body.get("text") or "")[:40],
                    (message.get("sender") or {}).get("user_id"),
                )
                restored = dict(update)
                restored["message"] = message
                restored["chat_id"] = chat_id
                return restored

            if attempt < RESTORE_ATTEMPTS:
                await asyncio.sleep(RESTORE_DELAY_SECONDS)

        logger.warning(
            "Не удалось восстановить сообщение (ts=%s) после %s попыток",
            event_ts,
            RESTORE_ATTEMPTS,
        )
        return update

    def remember_message_id(self, mid: str | None) -> None:
        """Запомнить обработанный ``mid`` — чтобы не восстановить его повторно."""
        if not mid:
            return
        if mid in self._seen_mids:
            self._seen_mids.remove(mid)
        self._seen_mids.append(mid)
        # Оставляем только последние SEEN_MIDS_LIMIT элементов.
        if len(self._seen_mids) > SEEN_MIDS_LIMIT:
            del self._seen_mids[: len(self._seen_mids) - SEEN_MIDS_LIMIT]


    def remember_chat(self, chat_id: int | None) -> None:
        """Запомнить chat_id — он нужен для восстановления голосовых событий."""
        if not chat_id:
            return
        if chat_id in self._known_chats:
            self._known_chats.remove(chat_id)
        self._known_chats.insert(0, chat_id)
        del self._known_chats[20:]

    @staticmethod
    def _extract_actor(update: dict[str, Any], update_type: str) -> dict[str, Any]:
        """Вернуть объект пользователя, который инициировал событие."""
        if update_type == "message_callback":
            callback_user = (update.get("callback") or {}).get("user") or {}
            if callback_user.get("user_id"):
                return callback_user
        if update_type in {"bot_started", "bot_stopped", "dialog_removed"}:
            event_user = update.get("user") or {}
            if event_user.get("user_id"):
                return event_user
        return extract_sender(update) or {}

    # --- внутренняя логика ------------------------------------------------

    async def _dispatch(
        self,
        update: dict[str, Any],
        update_type: str,
        sender: dict[str, Any],
        sender_user_id: Any,
    ) -> None:
        if not sender_user_id:
            logger.warning("Событие %s без user_id пользователя", update_type)
            return
        max_user_id = int(sender_user_id)

        user, _created = await self.users.ensure_user(
            max_user_id,
            username=sender.get("username"),
            first_name=sender.get("first_name"),
        )
        state = await self.states.get(user.id)

        ctx = Context(
            max_user_id=max_user_id,
            user=user,
            state=state,
            db=self.db,
            api=self.api,
            settings=self.settings,
            users=self.users,
            categories=self.categories,
            states=self.states,
            raw=update,
        )
        ctx.event = self._classify(update, update_type)
        ctx.attachments = extract_attachments(update)
        ctx.message_id = extract_message_id(update)
        ctx.chat_id = extract_chat_id(update)
        self.remember_chat(ctx.chat_id)
        if ctx.chat_id:
            try:
                await self.users.set_last_chat_id(user.id, ctx.chat_id)
            except Exception:
                logger.debug("Не удалось сохранить chat_id", exc_info=True)
        if ctx.attachments:
            logger.info(
                "Событие %s от %s: вложения=%s, тип=%s",
                update_type,
                sender_user_id,
                [item.get("type") for item in ctx.attachments],
                ctx.event,
            )

        if ctx.event == "callback":
            callback = update.get("callback") or {}
            ctx.callback_id = callback.get("callback_id") or callback.get("id")
            action, args = parse_payload(callback.get("payload"))
            ctx.text = action
            ctx.args = args
        elif ctx.event == "system":
            ctx.text = update_type
        else:
            ctx.text = extract_text(update)
            # Аудио не распознано как голосовое — обрабатываем как обычный текст.
            if ctx.event == "voice" and find_voice_attachment(ctx.attachments) is None:
                ctx.event = "message"

        # Незавершённый онбординг: пользователь не может работать с ботом,
        # пока не выбрал валюту и часовой пояс.
        if (
            not user.onboarding_completed
            and ctx.event in {"message", "command", "voice"}
            and (ctx.event != "command" or ctx.text not in {"/start", "/menu"})
        ):
            from bot.handlers.start import start_handler

            result = await start_handler(ctx)
            prompt = result[0] if isinstance(result, list) else (result or main_menu_screen())
            await self.send_screens(ctx, [prompt])
            return

        views = await router.dispatch(ctx)

        if ctx.callback_id:
            await self._answer_callback(ctx, views)
        if views:
            await self.send_screens(ctx, views)

    @staticmethod
    def _classify(update: dict[str, Any], update_type: str) -> str:
        if update_type == "message_callback":
            return "callback"
        if update_type in MESSAGE_EVENTS:
            attachments = extract_attachments(update)
            if find_voice_attachment(attachments) is not None:
                return "voice"
            text = extract_text(update)
            return "command" if text.startswith("/") else "message"
        if update_type in SYSTEM_EVENTS:
            return "system"
        return "system"

    async def _answer_callback(self, ctx: Context, views: list[ScreenView]) -> None:
        """Ответ на нажатие кнопки: убирает «часики» и показывает тост."""
        toast = next((view.toast for view in views if view.toast), None)
        try:
            await ctx.api.answer_callback(str(ctx.callback_id), notification=toast)
        except MaxAPIError as exc:
            logger.debug("answer_callback не удался: %s", exc)

    # --- отправка ---------------------------------------------------------

    async def send_screens(self, ctx: Context, views: list[ScreenView]) -> None:
        """Отправить экраны пользователю и сохранить состояние после последнего."""
        last: ScreenView | None = None
        for index, view in enumerate(views):
            if index > 0:
                await asyncio.sleep(MESSAGE_DELAY_SECONDS)
            await self.send_screen(ctx, view)
            last = view

        if last is not None and last.next_screen is not None:
            await self.states.set(
                ctx.user.id,
                last.next_screen,
                last.state_data if last.state_data is not None else ctx.state.data,
            )

    async def send_screen(self, ctx: Context, view: ScreenView) -> None:
        """Отправить одно сообщение-экран."""
        attachments = view.keyboard.to_attachments() + list(view.attachments)
        logger.debug("Отправка (user=%s): %r", ctx.max_user_id, view.text[:80])
        try:
            await ctx.api.send_message(
                user_id=ctx.max_user_id,
                text=view.text,
                attachments=attachments or None,
                format=view.parse_mode,
            )
        except MaxAPIError as exc:
            logger.error(
                "Не удалось отправить сообщение пользователю %s: %s", ctx.max_user_id, exc
            )


async def build_dispatcher(
    db: Database, api: MaxClient, settings: Settings | None = None
) -> Dispatcher:
    """Собрать диспетчер с зарегистрированными обработчиками."""
    import bot.handlers  # noqa: F401 - регистрирует обработчики в роутере

    dispatcher = Dispatcher(db=db, api=api, settings=settings or get_settings())

    # Предзаполняем известные chat_id из БД — восстановление голосовых
    # работает сразу после старта бота.
    # ВАЖНО: chat_id диалога НЕ равен max_user_id (проверено: 461841194
    # против 72910765), поэтому берём реально сохранённый last_chat_id,
    # а max_user_id — только как резерв для ещё не обновлённых записей.
    try:
        rows = await db.fetch(
            "SELECT max_user_id, last_chat_id FROM users WHERE is_active = TRUE "
            "ORDER BY last_seen_at DESC NULLS LAST LIMIT 20"
        )
        for row in rows:
            chat_id = row["last_chat_id"] or row["max_user_id"]
            dispatcher.remember_chat(int(chat_id))
        logger.info("Известные чаты для восстановления событий: %s", dispatcher._known_chats)
    except Exception as exc:
        logger.warning("Не удалось предзаполнить chat_id: %s", exc)

    return dispatcher

