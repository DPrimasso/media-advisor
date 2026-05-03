"""Channel registry, video lists, pending inbox, video-dates — SQLite canonical store."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from media_advisor.db.repository import (
    APP_DOC_PENDING,
    APP_DOC_VIDEO_DATES,
    fetch_app_state_doc_json,
    fetch_channel_registry_json,
    fetch_channel_video_list_urls_json,
    upsert_app_state_doc,
    upsert_channel_registry,
    upsert_channel_video_list,
)
from media_advisor.db.session import session_scope
from media_advisor.io.json_io import read_json
from media_advisor.io.paths import channels_config_path, pending_path, video_dates_cache_path


def load_channels_config_dict(root: Path) -> dict[str, Any]:
    """Full channels.json payload as dict. Seeds DB from disk once if empty."""
    with session_scope(root) as session:
        raw = fetch_channel_registry_json(session)
        if raw:
            try:
                data = json.loads(raw)
                return data if isinstance(data, dict) else {"channels": []}
            except json.JSONDecodeError:
                pass
        p = channels_config_path(root)
        if p.exists():
            try:
                data = read_json(p)
                if isinstance(data, dict):
                    upsert_channel_registry(session, data)
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        return {"channels": []}


def save_channels_config_dict(root: Path, data: dict[str, Any]) -> None:
    with session_scope(root) as session:
        upsert_channel_registry(session, data)


def read_channel_video_urls(root: Path, list_key: str) -> list[str]:
    """list_key is the video_list filename (e.g. fabrizio-romano-italiano.json)."""
    with session_scope(root) as session:
        uj = fetch_channel_video_list_urls_json(session, list_key)
        if uj:
            try:
                u = json.loads(uj)
                if isinstance(u, list):
                    return [str(x) for x in u]
            except json.JSONDecodeError:
                pass
        p = root / "channels" / list_key
        if p.exists():
            try:
                data = read_json(p)
                if isinstance(data, list):
                    urls = [str(x) for x in data]
                    upsert_channel_video_list(session, list_key, urls)
                    return urls
            except (OSError, json.JSONDecodeError):
                pass
        return []


def write_channel_video_urls(root: Path, list_key: str, urls: list[str]) -> None:
    with session_scope(root) as session:
        upsert_channel_video_list(session, list_key, urls)


def load_pending_dict(root: Path) -> dict[str, Any]:
    with session_scope(root) as session:
        raw = fetch_app_state_doc_json(session, APP_DOC_PENDING)
        if raw:
            try:
                d = json.loads(raw)
                return d if isinstance(d, dict) else {"fetched_at": None, "items": []}
            except json.JSONDecodeError:
                pass
        p = pending_path(root)
        if p.exists():
            try:
                d = read_json(p)
                if isinstance(d, dict):
                    upsert_app_state_doc(session, APP_DOC_PENDING, d)
                    return d
            except (OSError, json.JSONDecodeError):
                pass
        return {"fetched_at": None, "items": []}


def save_pending_dict(root: Path, data: dict[str, Any]) -> None:
    with session_scope(root) as session:
        upsert_app_state_doc(session, APP_DOC_PENDING, data)


def load_video_dates_dict(root: Path) -> dict[str, str]:
    with session_scope(root) as session:
        raw = fetch_app_state_doc_json(session, APP_DOC_VIDEO_DATES)
        if raw:
            try:
                d = json.loads(raw)
                if isinstance(d, dict):
                    return {str(k): str(v) for k, v in d.items()}
            except json.JSONDecodeError:
                pass
        p = video_dates_cache_path(root)
        if p.exists():
            try:
                d = read_json(p)
                if isinstance(d, dict):
                    norm = {str(k): str(v) for k, v in d.items()}
                    upsert_app_state_doc(session, APP_DOC_VIDEO_DATES, norm)
                    return norm
            except (OSError, json.JSONDecodeError):
                pass
        return {}


def save_video_dates_dict(root: Path, data: dict[str, str]) -> None:
    with session_scope(root) as session:
        upsert_app_state_doc(session, APP_DOC_VIDEO_DATES, dict(data))
