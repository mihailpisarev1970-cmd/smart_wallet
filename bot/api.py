"""Низкоуровневый HTTP-клиент MAX Bot API.

Особенности платформы (см. https://dev.max.ru/docs-api):
* домен ``platform-api2.max.ru``;
* токен передаётся **только** в заголовке ``Authorization: <token>``
  (передача через query-параметры больше не поддерживается);
* лимит — не более 2 сообщений в секунду в один диалог;
* 429 — превышено количество запросов (нужен retry с задержкой).

Модуль не знает о бизнес-логике: он только выполняет запросы
и приводит ошибки платформы к исключениям.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from bot.utils.tls import verify_option

logger = logging.getLogger(__name__)

#: Сколько раз повторять запрос при 429/5xx/сетевой ошибке.
DEFAULT_RETRIES = 3
#: Базовая пауза перед повтором (умножается на номер попытки).
RETRY_BASE_DELAY = 1.0


class MaxAPIError(Exception):
    """Ошибка при обращении к MAX Bot API."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class MaxAuthError(MaxAPIError):
    """401 — некорректный или недействительный токен."""


class MaxRateLimitError(MaxAPIError):
    """429 — превышено количество запросов."""


class MaxClient:
    """Асинхронный клиент MAX Bot API.

    Пример::

        async with MaxClient(token, base_url) as client:
            me = await client.get_me()
            await client.send_message(user_id=123, text="Привет!")
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://platform-api2.max.ru",
        *,
        timeout: float = 40.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={
                "Authorization": token,
                "Accept": "application/json",
            },
            # MAX API подписан сертификатом НУЦ Минцифры — подмешиваем его в CA.
            verify=verify_option(),
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> MaxClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        retries: int = DEFAULT_RETRIES,
    ) -> dict[str, Any]:
        """Выполнить запрос с ретраями и привести ошибки к исключениям."""
        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            try:
                response = await self._http.request(
                    method, f"/{path.lstrip('/')}", params=clean_params, json=json
                )
            except httpx.TimeoutException as exc:
                last_error = MaxAPIError(f"Таймаут запроса {method} /{path}: {exc}")
                logger.warning("MAX API timeout (%s /%s), попытка %s", method, path, attempt)
            except httpx.HTTPError as exc:
                last_error = MaxAPIError(f"Сетевая ошибка {method} /{path}: {exc}")
                logger.warning("MAX API network error (%s /%s): %s", method, path, exc)
            else:
                if response.status_code < 400:
                    return self._parse(response)

                payload = self._safe_json(response)
                snippet = str(payload)[:500]
                if response.status_code == 401:
                    raise MaxAuthError(
                        "MAX API: некорректный или недействительный токен (401).",
                        status_code=401,
                        payload=payload,
                    )
                if response.status_code == 429:
                    last_error = MaxRateLimitError(
                        f"MAX API: превышен лимит запросов (429). {snippet}",
                        status_code=429,
                        payload=payload,
                    )
                elif response.status_code >= 500:
                    last_error = MaxAPIError(
                        f"MAX API: ошибка сервера {response.status_code}. {snippet}",
                        status_code=response.status_code,
                        payload=payload,
                    )
                else:
                    # 400/404/405 — повторять бессмысленно.
                    raise MaxAPIError(
                        f"MAX API: {method} /{path} → {response.status_code}. {snippet}",
                        status_code=response.status_code,
                        payload=payload,
                    )

            if attempt < retries:
                await asyncio.sleep(RETRY_BASE_DELAY * attempt)

        raise last_error or MaxAPIError(f"MAX API: запрос {method} /{path} не удался")

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text

    def _parse(self, response: httpx.Response) -> dict[str, Any]:
        payload = self._safe_json(response)
        return payload if isinstance(payload, dict) else {"result": payload}

    # --- методы API -----------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        """GET /me — информация о боте."""
        return await self._request("GET", "me")

    async def set_commands(self, commands: list[dict[str, str]]) -> dict[str, Any]:
        """PATCH /me/commands — команды в подсказках MAX.

        ``commands`` — список ``{"name": "start", "description": "..."}``
        (до 32 штук, ``name`` без слэша). Пустой список удаляет все команды.
        Показываются при вводе «/» в диалоге с ботом (iOS, Android, десктоп).
        """
        payload = [
            {"name": item["name"][:64], "description": (item.get("description") or "")[:128]}
            for item in commands[:32]
        ]
        return await self._request("PATCH", "me/commands", json={"commands": payload})


    async def get_updates(
        self,
        *,
        marker: int | None = None,
        limit: int | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """GET /updates — long polling.

        Ответ: ``{"updates": [...], "marker": <int>}``.
        ``marker`` указывает на следующее ожидаемое обновление.
        """
        params: dict[str, Any] = {"limit": limit, "timeout": timeout, "marker": marker}
        return await self._request("GET", "updates", params=params)

    async def send_message(
        self,
        *,
        user_id: int | None = None,
        chat_id: int | None = None,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        format: str | None = None,
        notify: bool = True,
    ) -> dict[str, Any]:
        """POST /messages — отправить сообщение в диалог или чат."""
        params = {"user_id": user_id, "chat_id": chat_id}
        body: dict[str, Any] = {"notify": notify}
        if text is not None:
            body["text"] = text
        if attachments:
            body["attachments"] = attachments
        if format:
            body["format"] = format
        return await self._request("POST", "messages", params=params, json=body)

    async def edit_message(
        self,
        message_id: str,
        *,
        text: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        format: str | None = None,
    ) -> dict[str, Any]:
        """PUT /messages?message_id=... — отредактировать сообщение."""
        body: dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if attachments:
            body["attachments"] = attachments
        if format:
            body["format"] = format
        return await self._request("PUT", "messages", params={"message_id": message_id}, json=body)

    async def delete_message(self, message_id: str) -> dict[str, Any]:
        """DELETE /messages?message_id=... — удалить сообщение."""
        return await self._request("DELETE", "messages", params={"message_id": message_id})

    async def answer_callback(
        self, callback_id: str, *, notification: str | None = None
    ) -> dict[str, Any]:
        """POST /answers?callback_id=... — ответ на нажатие кнопки.

        Убирает «часики» на кнопке и (опционально) показывает всплывающее
        уведомление пользователю. Ответ на callback не является критичным:
        сообщение-реакцию бот отправляет обычным POST /messages.
        """
        body: dict[str, Any] = {}
        if notification:
            body["notification"] = notification
        return await self._request(
            "POST", "answers", params={"callback_id": callback_id}, json=body, retries=1
        )

    # --- webhook-подписки -----------------------------------------------

    async def subscribe_webhook(
        self, url: str, update_types: list[str] | None = None
    ) -> dict[str, Any]:
        """POST /subscriptions — подписаться на события через Webhook."""
        body: dict[str, Any] = {"url": url}
        if update_types:
            body["update_types"] = update_types
        return await self._request("POST", "subscriptions", json=body)

    async def get_subscriptions(self) -> dict[str, Any]:
        """GET /subscriptions — список webhook-подписок."""
        return await self._request("GET", "subscriptions")

    async def unsubscribe_webhook(self, url: str) -> dict[str, Any]:
        """DELETE /subscriptions?url=... — отписаться от webhook."""
        return await self._request("DELETE", "subscriptions", params={"url": url})

    # --- медиа -----------------------------------------------------------

    async def get_messages(
        self, chat_id: int, *, count: int = 20, message_ids: list[str] | None = None
    ) -> dict[str, Any]:
        """GET /messages?chat_id=... — история сообщений чата (новые первыми).

        Нужен, когда MAX присылает ``message_created`` без поля ``message``
        (так приходят голосовые сообщения при long polling).
        """
        params: dict[str, Any] = {"chat_id": chat_id, "count": count}
        if message_ids:
            params["message_ids"] = ",".join(str(item) for item in message_ids)
        return await self._request("GET", "messages", params=params)

    async def get_upload_url(self, upload_type: str = "file") -> dict[str, Any]:
        """POST /uploads?type=... — получить URL для загрузки вложения."""
        return await self._request("POST", "uploads", params={"type": upload_type})

    async def post_to_upload_url(
        self, upload_url: str, content: bytes, filename: str
    ) -> dict[str, Any]:
        """Загрузить файл по URL из ``/uploads``; вернуть ответ (токен вложения)."""
        from bot.utils.tls import verify_option

        if upload_url.startswith("/"):
            upload_url = f"{self._base_url}{upload_url}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(180.0, connect=20.0), verify=verify_option()
        ) as http:
            response = await http.post(
                upload_url,
                headers={"Authorization": self._token},
                files={"data": (filename, content, "application/octet-stream")},
            )
        if response.status_code >= 400:
            raise MaxAPIError(
                f"Загрузка файла не удалась: {response.status_code} {response.text[:300]}",
                status_code=response.status_code,
            )
        return self._parse(response)

    async def download_attachment(self, url: str) -> bytes:
        """Скачать вложение (голосовое, аудио, файл) по URL из события.

        MAX может отдавать вложения по защищённому адресу: сначала пробуем
        с заголовком ``Authorization`` (как в Bot API), затем — без него.
        """
        from bot.utils.tls import verify_option

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0), follow_redirects=True, verify=verify_option()
        ) as client:
            for headers in ({"Authorization": self._token}, {}):
                response = await client.get(url, headers=headers)
                if response.status_code < 400 and response.content:
                    return response.content
                logger.warning(
                    "Скачивание вложения %s → HTTP %s (auth=%s)",
                    url[:80],
                    response.status_code,
                    bool(headers),
                )
        raise MaxAPIError(
            f"Не удалось скачать вложение: HTTP {response.status_code} — {response.text[:200]}",
            status_code=response.status_code,
        )

