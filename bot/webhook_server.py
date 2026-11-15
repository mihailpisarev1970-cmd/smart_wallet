"""Единый HTTP-сервер: события MAX (webhook) + уведомления ЮKassa.

Один процесс закрывает всё, что нужно на сервере:

===========================  ============================================
Маршрут                      Назначение
===========================  ============================================
``POST /webhook/max/<secret>``  события MAX (сообщения, callback, старт)
``GET  /healthz``               проверка живости для nginx/systemd
``POST /yookassa/webhook``      уведомление ЮKassa об оплате
``GET  /pay/success``           страница «оплата прошла»
``GET  /pay/fail``              страница «оплата не выполнена»
===========================  ============================================

Почему webhook, а не long polling:

* MAX присылает голосовые в polling **без тела** (``message`` вообще нет),
  а ``GET /messages`` их не отдаёт — восстановить невозможно;
* в webhook событие приходит целиком, с ``chat_id`` и ``user_id``;
* нет постоянных запросов 24/7 — нагрузка только на события;
* MAX повторяет доставку, если ответ не 200;
* HTTPS-эндпоинт всё равно нужен для ЮKassa — теперь он общий.

Запуск::

    python -m bot.webhook_server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from aiohttp import web

from bot.api import MaxAuthError, MaxClient
from bot.config import Settings, get_settings
from bot.db import Database
from bot.dispatcher import Dispatcher, build_dispatcher
from bot.logging_setup import setup_logging
from bot.services.subscription import SubscriptionService
from bot.services.yookassa import YooKassaClient, YooKassaConfig
from bot.utils.ratelimit import RateLimiter
from bot.utils.tls import build_ca_bundle

logger = logging.getLogger(__name__)


def _extract_sender_id(payload: dict[str, Any]) -> int | None:
    """Достать ``user_id`` отправителя из любого типа события MAX.

    Структура различается: у сообщений это ``message.sender.user_id``,
    у callback — ``callback.user.user_id``. Возвращаем ``None``, если
    определить не удалось (тогда событие не лимитируется).
    """
    message = payload.get("message")
    if isinstance(message, dict):
        sender = message.get("sender")
        if isinstance(sender, dict):
            value = sender.get("user_id")
            if isinstance(value, int):
                return value
    callback = payload.get("callback")
    if isinstance(callback, dict):
        user = callback.get("user")
        if isinstance(user, dict):
            value = user.get("user_id")
            if isinstance(value, int):
                return value
    value = payload.get("user_id")
    return value if isinstance(value, int) else None

#: Предельный размер тела вебхука (защита от мусора).
MAX_BODY_BYTES = 1024 * 1024

#: Страница успешной оплаты.
SUCCESS_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Оплата прошла</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f8fa;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#fff;padding:40px 48px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);
text-align:center;max-width:420px}}h1{{color:#1a7f37;margin:0 0 12px}}
p{{color:#57606a;line-height:1.5}}</style></head>
<body><div class="card"><h1>✅ Оплата прошла</h1>
<p>{message}</p><p>Вернитесь в мессенджер MAX — подписка активируется автоматически.</p>
</div></body></html>"""

#: Страница неудачной оплаты.
FAIL_HTML = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<title>Оплата не выполнена</title>
<style>body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f8fa;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{background:#fff;padding:40px 48px;border-radius:16px;box-shadow:0 4px 24px rgba(0,0,0,.08);
text-align:center;max-width:420px}}h1{{color:#cf222e;margin:0 0 12px}}
p{{color:#57606a;line-height:1.5}}</style></head>
<body><div class="card"><h1>Оплата не выполнена</h1>
<p>{message}</p><p>Можно вернуться в MAX и попробовать снова.</p></div></body></html>"""



class WebhookApp:
    """Состояние приложения: БД, API-клиент, диспетчер, настройки."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db: Database | None = None
        self.api: MaxClient | None = None
        self.dispatcher: Dispatcher | None = None
        self.yookassa = YooKassaClient(YooKassaConfig.from_settings(settings))
        #: Фоновые задачи обработки событий (чтобы ответить MAX сразу).
        self.tasks: set[asyncio.Task[None]] = set()
        #: Ограничение частоты входящих событий (ТЗ п. 11).
        self._limiter = RateLimiter()

    # --- жизненный цикл ---------------------------------------------------

    async def start(self) -> None:
        """Подключиться к БД и подготовить зависимости."""
        self.db = Database(
            self.settings.database_url,
            min_size=self.settings.db_pool_min_size,
            max_size=self.settings.db_pool_max_size,
        )
        await self.db.connect()
        ok, version = await self.db.check_connection()
        if not ok:
            raise RuntimeError(f"Нет подключения к PostgreSQL: {version}")
        logger.info("PostgreSQL: %s", version.split(",")[0])

        self.api = MaxClient(
            self.settings.max_bot_token,
            self.settings.max_api_base_url,
            timeout=self.settings.max_http_timeout_seconds,
        )
        me = await self.api.get_me()
        logger.info(
            "Бот: %s (@%s), user_id=%s",
            me.get("name"),
            me.get("username"),
            me.get("user_id"),
        )
        self.dispatcher = await build_dispatcher(self.db, self.api, self.settings)

        # Команды в подсказках MAX («/» в диалоге с ботом). Решает проблему
        # «Хотите продолжить чат с ботом?» — пользователь сразу видит /start.
        from bot.commands import register_commands

        await register_commands(self.api)

    async def stop(self) -> None:
        """Дождаться фоновых задач и закрыть соединения."""
        if self.tasks:
            logger.info("Ожидаю завершения %s задач…", len(self.tasks))
            await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.api is not None:
            await self.api.close()
        if self.db is not None:
            await self.db.close()

    # --- обработка событий ------------------------------------------------

    def schedule_event(self, update: dict[str, Any]) -> None:
        """Запустить обработку события в фоне и сразу ответить MAX.

        MAX ждёт быстрый ответ; если обработка займёт больше таймаута, он
        повторит доставку. Поэтому тяжёлую работу (STT, LLM) выносим в фон —
        идемпотентность по ``mid``/``callback_id`` защищает от дублей.
        """

        async def runner() -> None:
            try:
                assert self.dispatcher is not None
                await self.dispatcher.handle_update(update)
            except Exception:
                logger.exception(
                    "Ошибка обработки события %s", update.get("update_type")
                )

        task = asyncio.create_task(runner())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    # --- обработчики маршрутов -------------------------------------------

    async def handle_max_webhook(self, request: web.Request) -> web.Response:
        """Принять событие MAX и обработать его в фоне."""
        try:
            payload = await request.json()
        except Exception:
            logger.warning("Вебхук MAX: некорректный JSON")
            return web.json_response({"ok": False}, status=400)

        update_type = payload.get("update_type")
        has_message = bool(payload.get("message"))

        # ТЗ п. 11: ограничение частоты. Флуд от одного пользователя
        # отбрасываем, но всё равно отвечаем 200 — иначе MAX будет
        # повторять доставку и усилит нагрузку.
        sender_id = _extract_sender_id(payload)
        if sender_id is not None and not self._limiter.allow(sender_id):
            logger.warning("Вебхук MAX: слишком часто от user_id=%s — пропуск", sender_id)
            return web.json_response({"ok": True})

        logger.info(
            "Вебхук MAX: type=%s, has_message=%s, ts=%s",
            update_type,
            has_message,
            payload.get("timestamp"),
        )
        if has_message:
            body = (payload.get("message") or {}).get("body") or {}
            attachments = body.get("attachments") or []
            logger.info(
                "  mid=%s, вложения=%s, текст=%r",
                body.get("mid"),
                [item.get("type") for item in attachments if isinstance(item, dict)],
                (body.get("text") or "")[:40],
            )
            # Для отладки голосовых: сохраняем полную структуру вложения.
            for item in attachments:
                if isinstance(item, dict) and item.get("type") in {"audio", "voice", "file"}:
                    try:
                        dump_dir = Path("logs") / "attachments"
                        dump_dir.mkdir(parents=True, exist_ok=True)
                        stamp = int(payload.get("timestamp") or 0)
                        dump_file = dump_dir / f"{stamp}_{item.get('type')}.json"
                        dump_file.write_text(
                            json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8"
                        )
                        payload_data = item.get("payload") or {}
                        logger.info(
                            "    вложение %s сохранено: %s (url=%s, duration=%s, "
                            "transcription=%s)",
                            item.get("type"),
                            dump_file,
                            str(payload_data.get("url"))[:90],
                            payload_data.get("duration"),
                            bool(payload_data.get("transcription")),
                        )
                    except Exception:
                        logger.debug("Не удалось сохранить вложение", exc_info=True)

        self.schedule_event(payload)
        # MAX ожидает 200; тело ответа не важно.
        return web.json_response({"ok": True})

    async def handle_yookassa_webhook(self, request: web.Request) -> web.Response:
        """Уведомление ЮKassa: активировать подписку при успешной оплате.

        ЮKassa присылает JSON вида::

            {"type": "notification",
             "event": "payment.succeeded",
             "object": {"id": "...", "status": "succeeded",
                        "paid": true, "amount": {"value": "210.00"}}}

        Отвечаем 200 всегда, когда событие обработано (в т.ч. «уже активно»),
        иначе ЮKassa будет повторять доставку.
        """
        try:
            payload = await request.json()
        except Exception:
            logger.warning("ЮKassa: некорректный JSON в уведомлении")
            return web.json_response({"ok": False}, status=400)

        event = str(payload.get("event") or "")
        payment = payload.get("object") or {}
        payment_id = str(payment.get("id") or "")
        status = str(payment.get("status") or "")
        paid = bool(payment.get("paid"))
        amount = (payment.get("amount") or {}).get("value")

        logger.info(
            "ЮKassa webhook: event=%s payment_id=%s status=%s paid=%s amount=%s",
            event,
            payment_id,
            status,
            paid,
            amount,
        )

        if event != "payment.succeeded" or not payment_id:
            # Прочие события (canceled, waiting_for_capture) не активируют подписку.
            return web.json_response({"ok": True})

        assert self.db is not None
        service = SubscriptionService(
            self.db, self.yookassa, days=self.settings.ai_subscription_days
        )
        ok, message = await service.activate_by_payment_id(payment_id, amount)
        if not ok:
            # Платёж не найден/сумма не совпала — ЮKassa повторит запрос.
            logger.warning("ЮKassa: платёж %s не активирован (%s)", payment_id, message)
            return web.Response(status=500, text="internal error")

        logger.info("ЮKassa: подписка по платежу %s активирована (%s)", payment_id, message)
        return web.json_response({"ok": True})

    async def handle_pay_success(self, request: web.Request) -> web.Response:
        from bot.payment_pages import render_paid_page

        return web.Response(text=render_paid_page(), content_type="text/html")

    async def handle_pay_fail(self, request: web.Request) -> web.Response:
        from bot.payment_pages import render_cancel_page

        return web.Response(text=render_cancel_page(), content_type="text/html")

    async def handle_pay_page(self, request: web.Request) -> web.Response:
        """GET /pay/<payment_id> — брендированная страница оплаты.

        Показывает сумму и кнопку «Оплатить», ведущую на ``confirmation_url``
        ЮKassa. Ссылка запрашивается заново — исходная живёт ограниченное время.
        """
        from bot.payment_page import find_payment, resolve_payment_url
        from bot.payment_pages import (
            render_error_page,
            render_not_found_page,
            render_paid_page,
            render_payment_page,
        )
        from bot.utils.money import format_money

        payment_id = (request.match_info.get("payment_id") or "").strip()
        if not payment_id or self.db is None:
            return web.Response(text=render_not_found_page(), content_type="text/html", status=404)

        try:
            info = await find_payment(self.db, payment_id)
        except Exception as exc:
            logger.warning("Страница оплаты: ошибка чтения платежа %s: %s", payment_id, exc)
            return web.Response(text=render_error_page(), content_type="text/html", status=500)

        if info is None:
            logger.info("Страница оплаты: платёж %s не найден в БД", payment_id)
            return web.Response(text=render_not_found_page(), content_type="text/html", status=404)

        if info.already_paid:
            return web.Response(text=render_paid_page(), content_type="text/html")

        if self.yookassa is None:
            return web.Response(text=render_error_page(), content_type="text/html", status=500)

        url = await resolve_payment_url(self.yookassa, payment_id)
        if not url:
            logger.info("Страница оплаты: у платежа %s нет активной ссылки", payment_id)
            return web.Response(text=render_paid_page(), content_type="text/html")

        amount_text = format_money(
            self.settings.ai_subscription_price_rub, currency=info.currency, with_currency=True
        )
        html_page = render_payment_page(
            amount_text=amount_text,
            days=self.settings.ai_subscription_days,
            payment_url=url,
        )
        logger.info("Страница оплаты: платёж %s показан", payment_id)
        return web.Response(text=html_page, content_type="text/html")

    async def handle_health(self, request: web.Request) -> web.Response:
        """Проверка живости: используется nginx/systemd/monitoring."""
        return web.json_response(
            {
                "status": "ok",
                "mode": self.settings.max_updates_mode,
                "db": self.db is not None,
                "tasks": len(self.tasks),
            }
        )


def build_app(state: WebhookApp) -> web.Application:
    """Собрать aiohttp-приложение с маршрутами."""
    app = web.Application(client_max_size=MAX_BODY_BYTES)

    # Путь вебхука содержит секрет: без него MAX-события не принимаются.
    secret = state.settings.max_webhook_secret
    if secret:
        webhook_path = f"/webhook/max/{secret}"
    else:
        webhook_path = "/webhook/max"
        logger.warning(
            "MAX_WEBHOOK_SECRET не задан — вебхук открыт по /webhook/max. "
            "Для production обязательно задайте секрет!"
        )

    app.router.add_post(webhook_path, state.handle_max_webhook)
    app.router.add_get("/healthz", state.handle_health)
    app.router.add_post("/yookassa/webhook", state.handle_yookassa_webhook)
    app.router.add_get("/pay/success", state.handle_pay_success)
    app.router.add_get("/pay/fail", state.handle_pay_fail)
    app.router.add_get("/pay/{payment_id}", state.handle_pay_page)

    logger.info(
        "Маршруты: POST %s, GET /healthz, POST /yookassa/webhook, /pay/{success,fail}",
        webhook_path,
    )
    return app


async def register_max_webhook(settings: Settings) -> bool:
    """Зарегистрировать публичный адрес вебхука в MAX (``POST /subscriptions``)."""
    url = settings.public_max_webhook_url
    if not url:
        logger.error(
            "Не задан публичный адрес вебхука (WEBHOOK_BASE_URL / MAX_WEBHOOK_URL) — "
            "авторегистрация пропущена"
        )
        return False

    async with MaxClient(
        settings.max_bot_token, settings.max_api_base_url, timeout=30.0
    ) as api:
        try:
            # Только события сообщений и callback — этого достаточно боту.
            result = await api.subscribe_webhook(
                url,
                update_types=[
                    "message_created",
                    "message_callback",
                    "message_edited",
                    "bot_started",
                    "bot_stopped",
                ],
            )
        except MaxAuthError:
            logger.critical("Токен бота недействителен — проверьте .env")
            return False
        except Exception as exc:
            logger.error("Не удалось зарегистрировать вебхук: %s", exc)
            return False

    logger.info("Вебхук зарегистрирован в MAX: %s → %s", url, result)
    return True


async def run_server(stop_event: asyncio.Event) -> int:
    """Запустить HTTP-сервер и держать его до сигнала остановки."""
    settings = get_settings()
    build_ca_bundle()

    state = WebhookApp(settings)
    await state.start()

    app = build_app(state)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, settings.webhook_host, settings.webhook_port)
    await site.start()
    logger.info(
        "Сервер слушает http://%s:%s (режим %s)",
        settings.webhook_host,
        settings.webhook_port,
        settings.max_updates_mode,
    )

    if settings.max_updates_mode == "webhook":
        await register_max_webhook(settings)

    try:
        await stop_event.wait()
    finally:
        logger.info("Останавливаю сервер…")
        await runner.cleanup()
        await state.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Webhook-сервер MAX + ЮKassa")
    parser.add_argument("--log-level", default=None, help="Уровень логирования")
    parser.add_argument(
        "--register-only",
        action="store_true",
        help="Только зарегистрировать вебхук в MAX и выйти",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    settings = get_settings()

    if args.register_only:
        build_ca_bundle()
        return 0 if asyncio.run(register_max_webhook(settings)) else 1

    stop_event = asyncio.Event()

    async def runner() -> int:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:  # Windows
                signal.signal(sig, lambda *_: stop_event.set())
        return await run_server(stop_event)

    try:
        return asyncio.run(runner())
    except KeyboardInterrupt:
        print("\nОстановлено")
        return 0


if __name__ == "__main__":
    sys.exit(main())


