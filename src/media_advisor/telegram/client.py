"""Telegram Bot API async client."""

from dataclasses import dataclass
from typing import Any

import httpx

TELEGRAM_API_BASE_URL = "https://api.telegram.org"
TELEGRAM_MESSAGE_MAX_LENGTH = 4096


class TelegramClientError(Exception):
    """Raised when Telegram sendMessage fails."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        telegram_error_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.telegram_error_code = telegram_error_code


@dataclass(slots=True)
class TelegramSendResult:
    chunks_sent: int
    message_ids: list[int]


def _chunk_message(text: str, max_length: int = TELEGRAM_MESSAGE_MAX_LENGTH) -> list[str]:
    """Split a long text into Telegram-safe chunks, preferring paragraph/line boundaries."""
    if max_length <= 0:
        raise ValueError("max_length must be > 0")
    if not text:
        return []
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    cursor = 0
    text_len = len(text)

    while cursor < text_len:
        remaining = text_len - cursor
        if remaining <= max_length:
            chunks.append(text[cursor:])
            break

        window_end = cursor + max_length
        split_at = text.rfind("\n\n", cursor + 1, window_end + 1)
        if split_at != -1:
            maybe_split = split_at + 2  # keep separator in the previous chunk when possible
            split_at = maybe_split if maybe_split <= window_end else split_at
        else:
            split_at = text.rfind("\n", cursor + 1, window_end + 1)
            if split_at != -1:
                maybe_split = split_at + 1  # keep newline in the previous chunk when possible
                split_at = maybe_split if maybe_split <= window_end else split_at

        if split_at == -1 or split_at <= cursor:
            split_at = window_end

        chunks.append(text[cursor:split_at])
        cursor = split_at

    return chunks


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        *,
        chat_id: str,
        thread_id: int | None = None,
        timeout: float = 20.0,
        base_url: str = TELEGRAM_API_BASE_URL,
    ) -> None:
        if not bot_token.strip():
            raise ValueError("bot_token cannot be empty")
        if not str(chat_id).strip():
            raise ValueError("chat_id cannot be empty")

        self._chat_id = chat_id
        self._thread_id = thread_id
        self._timeout = timeout
        self._send_url = f"{base_url.rstrip('/')}/bot{bot_token}/sendMessage"

    async def send_message(
        self,
        text: str,
        *,
        parse_mode: str | None = None,
        disable_web_page_preview: bool = False,
    ) -> TelegramSendResult:
        """Send text to Telegram, splitting over the 4096 chars hard limit."""
        chunks = _chunk_message(text)
        if not chunks:
            return TelegramSendResult(chunks_sent=0, message_ids=[])

        message_ids: list[int] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for chunk in chunks:
                payload: dict[str, Any] = {
                    "chat_id": self._chat_id,
                    "text": chunk,
                }
                if self._thread_id is not None:
                    payload["message_thread_id"] = self._thread_id
                if parse_mode:
                    payload["parse_mode"] = parse_mode
                if disable_web_page_preview:
                    payload["disable_web_page_preview"] = True

                try:
                    response = await client.post(self._send_url, json=payload)
                except httpx.RequestError as exc:
                    raise TelegramClientError(f"Telegram request failed: {exc}") from exc

                if not response.is_success:
                    body = self._decode_json(response)
                    message, error_code = self._extract_error(body, response)
                    raise TelegramClientError(
                        message,
                        status_code=response.status_code,
                        telegram_error_code=error_code,
                    )

                body = self._decode_json(response)
                if body is None:
                    raise TelegramClientError(
                        "Telegram returned invalid JSON",
                        status_code=response.status_code,
                    )
                if not isinstance(body, dict) or not body.get("ok"):
                    raise TelegramClientError(
                        self._extract_body_error_message(body),
                        status_code=response.status_code,
                        telegram_error_code=(
                            body.get("error_code")
                            if isinstance(body, dict) and isinstance(body.get("error_code"), int)
                            else None
                        ),
                    )

                result = body.get("result") if isinstance(body, dict) else None
                if isinstance(result, dict) and isinstance(result.get("message_id"), int):
                    message_ids.append(result["message_id"])

        return TelegramSendResult(chunks_sent=len(chunks), message_ids=message_ids)

    @staticmethod
    def _decode_json(response: httpx.Response) -> Any | None:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_error(body: Any, response: httpx.Response) -> tuple[str, int | None]:
        fallback = response.reason_phrase or f"HTTP {response.status_code}"
        error_code: int | None = None
        if isinstance(body, dict) and isinstance(body.get("error_code"), int):
            error_code = body["error_code"]
        message = TelegramClient._extract_body_error_message(body, fallback)
        return message, error_code

    @staticmethod
    def _extract_body_error_message(body: Any, fallback: str = "Telegram API returned an unknown error") -> str:
        if isinstance(body, dict):
            description = body.get("description")
            if isinstance(description, str) and description.strip():
                return description
        return fallback
