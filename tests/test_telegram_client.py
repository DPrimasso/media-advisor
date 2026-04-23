import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from media_advisor.telegram.client import TelegramClient, TelegramClientError, _chunk_message


def test_send_message_single_chunk() -> None:
    client = TelegramClient("token", chat_id="-100123")

    response = httpx.Response(200, json={"ok": True, "result": {"message_id": 101}})
    post_mock = AsyncMock(return_value=response)

    with patch("media_advisor.telegram.client.httpx.AsyncClient.post", post_mock):
        result = asyncio.run(client.send_message("hello"))

    assert result.chunks_sent == 1
    assert result.message_ids == [101]
    payload = post_mock.call_args.kwargs["json"]
    assert payload["chat_id"] == "-100123"
    assert payload["text"] == "hello"


def test_send_message_chunks_long_text() -> None:
    client = TelegramClient("token", chat_id="-100123")
    long_text = ("A" * 4096) + "\n\n" + ("B" * 20)

    response = httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
    post_mock = AsyncMock(return_value=response)

    with patch("media_advisor.telegram.client.httpx.AsyncClient.post", post_mock):
        result = asyncio.run(client.send_message(long_text))

    assert result.chunks_sent == 2
    assert post_mock.await_count == 2
    first_payload = post_mock.await_args_list[0].kwargs["json"]
    second_payload = post_mock.await_args_list[1].kwargs["json"]
    assert len(first_payload["text"]) <= 4096
    assert len(second_payload["text"]) <= 4096
    assert first_payload["text"] == "A" * 4096
    assert (first_payload["text"] + second_payload["text"]) == long_text
    assert second_payload["text"].endswith("B" * 20)


def test_send_message_rejects_chunked_parse_mode() -> None:
    client = TelegramClient("token", chat_id="-100123")
    long_text = ("A" * 4096) + "B"

    with pytest.raises(TelegramClientError) as exc_info:
        asyncio.run(client.send_message(long_text, parse_mode="MarkdownV2"))

    assert "Cannot safely chunk formatted messages" in str(exc_info.value)


def test_send_message_raises_contextual_error() -> None:
    client = TelegramClient("token", chat_id="-100123")
    response = httpx.Response(
        400,
        json={"ok": False, "error_code": 400, "description": "Bad Request: chat not found"},
    )
    post_mock = AsyncMock(return_value=response)

    with (
        patch("media_advisor.telegram.client.httpx.AsyncClient.post", post_mock),
        pytest.raises(TelegramClientError) as exc_info,
    ):
        asyncio.run(client.send_message("hello"))

    err = exc_info.value
    assert "chat not found" in str(err)
    assert err.status_code == 400
    assert err.telegram_error_code == 400


def test_send_message_raises_on_invalid_json_success() -> None:
    client = TelegramClient("token", chat_id="-100123")
    response = httpx.Response(200, content=b"<html>gateway</html>")
    post_mock = AsyncMock(return_value=response)

    with (
        patch("media_advisor.telegram.client.httpx.AsyncClient.post", post_mock),
        pytest.raises(TelegramClientError) as exc_info,
    ):
        asyncio.run(client.send_message("hello"))

    err = exc_info.value
    assert "invalid JSON" in str(err)
    assert err.status_code == 200


def test_chunk_message_splits_by_lines() -> None:
    text = "line-1\nline-2\nline-3"
    chunks = _chunk_message(text, max_length=10)
    assert "".join(chunks) == text
    assert all(len(chunk) <= 10 for chunk in chunks)


def test_chunk_message_preserves_newlines_exactly() -> None:
    text = ("A" * 8) + "\n\n" + ("B" * 8) + "\n" + ("C" * 8)
    chunks = _chunk_message(text, max_length=10)
    assert "".join(chunks) == text
