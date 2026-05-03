"""Transcript persistence — SQLite only (legacy JSON under data/transcripts/ is not updated)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from media_advisor.db.repository import (
    fetch_transcript_payload,
    transcript_exists_in_db,
    upsert_transcript,
)
from media_advisor.db.session import session_scope


def save_transcript_to_store(root: Path, channel_id: str, video_id: str, payload: dict[str, Any]) -> None:
    with session_scope(root) as session:
        upsert_transcript(session, channel_id, video_id, payload)


def db_upsert_transcript(root: Path, channel_id: str, video_id: str, payload: dict[str, Any]) -> None:
    """Alias for save_transcript_to_store (CLI compatibility)."""
    save_transcript_to_store(root, channel_id, video_id, payload)


def load_transcript_dict(root: Path, channel_id: str, video_id: str) -> dict[str, Any] | None:
    with session_scope(root, read_only=True) as session:
        return fetch_transcript_payload(session, channel_id, video_id)


def transcript_is_cached(root: Path, channel_id: str, video_id: str) -> bool:
    with session_scope(root, read_only=True) as session:
        return transcript_exists_in_db(session, channel_id, video_id)
