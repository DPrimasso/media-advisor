"""Telegram integration package."""

from media_advisor.telegram.client import TelegramClient, TelegramClientError, TelegramSendResult

__all__ = ["TelegramClient", "TelegramClientError", "TelegramSendResult"]
