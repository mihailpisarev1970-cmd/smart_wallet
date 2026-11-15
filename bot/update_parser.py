"""Извлечение данных из сырых событий MAX Bot API.

Структуры событий описаны в документации (объект ``Update``):
``update_type``, ``timestamp``, ``message`` (объект ``Message`` с ``body``,
``sender``, ``recipient``), ``callback`` (``callback_id``, ``payload``), ``user``.
"""

from __future__ import annotations

from typing import Any

#: События, которые считаются «сообщением пользователя».
MESSAGE_EVENTS = {"message_created", "message_edited"}

#: Служебные события, требующие только логирования (без ответа).
IGNORED_EVENTS = {
    "message_removed",
    "chat_title_changed",
    "dialog_cleared",
    "dialog_muted",
    "dialog_unmuted",
    "bot_added",
    "bot_removed",
    "user_added",
    "user_removed",
    "bot_admin_permissions_changed",
    "comment_created",
    "comment_edited",
    "comment_removed",
}


#: Недвусмысленные значения аргументов кнопок (валюта, период, тип, модель).
KNOWN_ARG_VALUES = frozenset(
    {
        "RUB", "USD", "EUR",
        "expense", "income",
        "today", "yesterday", "week", "month", "quarter", "custom",
        "overall", "category",
        "all", "amount", "comment",
    }
)


def parse_payload(payload: str | None) -> tuple[str, list[str]]:
    """Разобрать payload кнопки.

    В MAX ``callback_button(text, "tx:new", "expense")`` собирает payload
    ``tx:new:expense`` — действие и аргументы склеены через ``:``.
    Правила разбора:

    * аргумент — числовой id (``tx:cat:42`` → ``("tx:cat", ["42"])``);
    * аргумент — известный код (``onboarding:currency:RUB`` →
      ``("onboarding:currency", ["RUB"])``);
    * иначе payload целиком считается действием (``menu:main``,
      ``ai:save``) — так короткие «действия из двух слов» не ломаются.

    Возвращает ``(action, args)``.
    """
    if not payload:
        return "", []

    parts = payload.split(":")
    if len(parts) >= 2:
        last = parts[-1]
        is_numeric = last.replace("-", "").isdigit()
        if is_numeric or last in KNOWN_ARG_VALUES:
            return ":".join(parts[:-1]).strip(), [last.replace("|", ":")]

    return payload.strip(), []


def extract_text(update: dict[str, Any]) -> str:
    """Текст сообщения из события MAX."""
    message = update.get("message") or {}
    body = message.get("body") or {}
    return str(body.get("text") or "").strip()


def extract_message_id(update: dict[str, Any]) -> str | None:
    message = update.get("message") or {}
    mid = (message.get("body") or {}).get("mid") or message.get("mid")
    return str(mid) if mid else None


def extract_sender(update: dict[str, Any]) -> dict[str, Any]:
    message = update.get("message") or {}
    sender = message.get("sender") or update.get("user") or {}
    return sender if isinstance(sender, dict) else {}


def extract_chat_id(update: dict[str, Any]) -> int | None:
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    chat_id = recipient.get("chat_id") or update.get("chat_id")
    try:
        return int(chat_id) if chat_id is not None else None
    except (TypeError, ValueError):
        return None


def extract_attachments(update: dict[str, Any]) -> list[dict[str, Any]]:
    message = update.get("message") or {}
    body = message.get("body") or {}
    attachments = body.get("attachments") or message.get("attachments") or []
    return [item for item in attachments if isinstance(item, dict)]


def find_voice_attachment(attachments: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Найти голосовое сообщение или аудиофайл во вложениях.

    MAX присылает голосовые как ``type="audio"`` c ``payload.audio_type="voice"``
    либо как ``payload.body.voices``; поле с URL — ``url`` / ``payload.url``.
    """
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        payload = attachment.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        is_audio = attachment.get("type") in {"audio", "voice"}
        if not is_audio:
            continue
        if payload.get("audio_type") == "voice" or payload.get("body", {}).get("voices"):
            return attachment
        # Прочие аудиофайлы тоже поддерживаются (ТЗ п. 4.3).
        return attachment
    return None


def voice_url(attachment: dict[str, Any]) -> str | None:
    """URL аудиофайла для скачивания."""
    payload = attachment.get("payload") or {}
    for key in ("url", "audio_url"):
        value = payload.get(key) or attachment.get(key)
        if value:
            return str(value)
    return None


def voice_duration(attachment: dict[str, Any]) -> float | None:
    """Длительность аудио в секундах, если платформа её прислала."""
    payload = attachment.get("payload") or {}
    for key in ("duration", "duration_ms"):
        value = payload.get(key) or (payload.get("body") or {}).get(key)
        if value is None:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        return number / 1000 if key.endswith("_ms") else number
    return None


def voice_transcription(attachment: dict[str, Any]) -> str | None:
    """Готовая транскрипция от MAX (``payload.transcription``).

    MAX умеет сам расшифровывать голосовые и кладёт текст в
    ``payload.transcription``. Если он есть — не тратим запрос на STT.
    """
    payload = attachment.get("payload") or {}
    for key in ("transcription", "transcript", "recognized_text"):
        value = payload.get(key) or attachment.get(key)
        if value and isinstance(value, str) and value.strip():
            return value.strip()
    return None
