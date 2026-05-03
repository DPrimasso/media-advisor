"""SQLite storage layer smoke tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def sqlite_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "test.sqlite"
    monkeypatch.setenv("MEDIA_ADVISOR_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    return tmp_path


def test_transcript_roundtrip(sqlite_root: Path) -> None:
    from media_advisor.db.repository import list_transcript_video_ids
    from media_advisor.db.session import session_scope
    from media_advisor.io.transcript_storage import load_transcript_dict, save_transcript_to_store

    payload = {"video_id": "vid1", "transcript": [], "metadata": None}
    save_transcript_to_store(sqlite_root, "ch1", "vid1", payload)
    assert load_transcript_dict(sqlite_root, "ch1", "vid1") == payload
    with session_scope(sqlite_root, read_only=True) as session:
        pairs = list_transcript_video_ids(session, None)
    assert pairs == [("ch1", "vid1")]


def test_transcript_existing_pair_keys_batch(sqlite_root: Path) -> None:
    from media_advisor.db.repository import transcript_existing_pair_keys
    from media_advisor.db.session import session_scope
    from media_advisor.io.transcript_storage import save_transcript_to_store

    save_transcript_to_store(sqlite_root, "a", "v1", {"video_id": "v1", "transcript": []})
    with session_scope(sqlite_root, read_only=True) as session:
        have = transcript_existing_pair_keys(session, [("v1", "a"), ("v2", "a"), ("v1", "b")])
    assert have == {("a", "v1")}


def test_channel_registry_and_list(sqlite_root: Path) -> None:
    from media_advisor.io.channel_store import (
        load_channels_config_dict,
        read_channel_video_urls,
        write_channel_video_urls,
    )

    cfg = {"channels": [{"id": "c1", "name": "C", "order": 0, "video_list": "c1.json", "fetch_rule": None}]}
    from media_advisor.db.repository import upsert_channel_registry
    from media_advisor.db.session import session_scope

    with session_scope(sqlite_root) as session:
        upsert_channel_registry(session, cfg)

    assert load_channels_config_dict(sqlite_root) == cfg
    write_channel_video_urls(sqlite_root, "c1.json", ["https://www.youtube.com/watch?v=abcdefghijk"])
    assert read_channel_video_urls(sqlite_root, "c1.json") == [
        "https://www.youtube.com/watch?v=abcdefghijk"
    ]


def test_mercato_index_roundtrip(sqlite_root: Path) -> None:
    from datetime import UTC, datetime

    from media_advisor.mercato.aggregator import load_index
    from media_advisor.mercato.models import MercatoIndex

    idx = MercatoIndex(updated_at=datetime.now(UTC), tips=[])
    from media_advisor.mercato.analyzer import save_mercato_index

    save_mercato_index(sqlite_root, idx)
    loaded = load_index(sqlite_root)
    assert len(loaded.tips) == 0


def test_analysis_dump_script_smoke(sqlite_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from media_advisor.db.repository import upsert_channel_registry, upsert_video_analysis
    from media_advisor.db.session import session_scope
    from media_advisor.tools.dump_analysis_public import main as dump_main

    web = sqlite_root / "web" / "public" / "analysis"
    monkeypatch.setenv("MEDIA_ADVISOR_ROOT", str(sqlite_root))

    cfg = {"channels": [{"id": "c1", "name": "C", "order": 0, "video_list": "c1.json", "fetch_rule": None}]}
    with session_scope(sqlite_root) as session:
        upsert_channel_registry(session, cfg)
        upsert_video_analysis(
            session,
            "c1",
            "v1",
            {
                "video_id": "v1",
                "analyzed_at": "2026-01-01T00:00:00+00:00",
                "summary": "x",
                "topics": [],
                "claims": [],
            },
        )

    dump_main()
    idx = json.loads((web / "index.json").read_text(encoding="utf-8"))
    assert len(idx) == 1
    assert (web / "c1" / "v1.json").exists()
