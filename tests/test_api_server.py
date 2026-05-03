"""FastAPI server smoke tests (isolated reload per case via MEDIA_ADVISOR_* env)."""

from __future__ import annotations

import importlib
import json
import types
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from media_advisor.db.repository import MERCATO_BLOB_ALIASES, fetch_mercato_blob_raw
from media_advisor.db.session import session_scope
from media_advisor.models.pending import PendingResult


def _reload_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **env: str | None) -> types.ModuleType:
    monkeypatch.setenv("MEDIA_ADVISOR_ROOT", str(tmp_path))
    db = tmp_path / "api_test.sqlite"
    monkeypatch.setenv("MEDIA_ADVISOR_DATABASE_URL", f"sqlite:///{db.as_posix()}")
    for key, val in env.items():
        if val is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, val)
    import server.api as api

    return importlib.reload(api)


def test_health_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Stringhe vuote: sovrascrivono eventuale .env (pydantic-settings: env batte env_file).
    api = _reload_api(monkeypatch, tmp_path, TRANSCRIPT_API_KEY="", OPENAI_API_KEY="")
    c = TestClient(api.app)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_health_ready_query_and_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, tmp_path)
    c = TestClient(api.app)
    r = c.get("/api/health", params={"ready": 1})
    assert r.status_code == 200
    r2 = c.get("/api/health/ready")
    assert r2.status_code == 200
    assert r2.json().get("db") == "ok"


def test_health_ready_503_when_db_check_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, tmp_path)

    def boom() -> None:
        raise RuntimeError("db down")

    api._check_sqlite_ready = boom  # type: ignore[method-assign]
    c = TestClient(api.app)
    r = c.get("/api/health/ready")
    assert r.status_code == 503
    assert "database" in r.json()["detail"].lower()


def test_post_sync_requires_pipeline_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, tmp_path, TRANSCRIPT_API_KEY="", OPENAI_API_KEY="")
    c = TestClient(api.app)
    r = c.post("/api/sync")
    assert r.status_code == 500
    detail = r.json()["detail"]
    assert "TRANSCRIPT" in detail or "OPENAI" in detail


def test_fetch_now_requires_sync_header_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    api = _reload_api(
        monkeypatch,
        tmp_path,
        MEDIA_ADVISOR_SYNC_SECRET="s3cr3t",
        TRANSCRIPT_API_KEY="tk",
    )
    c = TestClient(api.app)
    r = c.post("/api/fetch-now")
    assert r.status_code == 401


def test_fetch_now_ok_with_header_and_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(
        monkeypatch,
        tmp_path,
        MEDIA_ADVISOR_SYNC_SECRET="s3cr3t",
        TRANSCRIPT_API_KEY="tk",
    )
    fake = PendingResult(items=[])
    with patch("media_advisor.fetch.run_fetch_new_videos", new=AsyncMock(return_value=fake)):
        c = TestClient(api.app)
        r = c.post("/api/fetch-now", headers={"X-Media-Advisor-Sync": "s3cr3t"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("items") == []


def test_mercato_aliases_persists_sqlite_blob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _reload_api(monkeypatch, tmp_path)
    c = TestClient(api.app)
    r = c.post(
        "/api/mercato/aliases",
        json={"alias": "goat", "canonical": "Test Player"},
    )
    assert r.status_code == 200
    with session_scope(tmp_path, read_only=True) as session:
        raw = fetch_mercato_blob_raw(session, MERCATO_BLOB_ALIASES)
    assert raw is not None
    data = json.loads(raw)
    assert data["custom"]["goat"] == "Test Player"
