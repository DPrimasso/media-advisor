"""MCP server — exposes index/query/channel_report tools.

Storage: SQLite with FTS5 for full-text search over claims + transcripts.
Run with: python -m media_advisor.mcp_server
Or add to Claude Code MCP config pointing to this module.

Tools:
  index_transcripts  — index all analysis JSON files into SQLite FTS5
  query              — full-text search across indexed claims
  channel_report     — summary report for a channel (all claims, top themes)
"""

import json
import sqlite3
from pathlib import Path
from typing import Any

# MCP server via FastMCP (mcp package) ----------------------------------------

try:
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-untyped]

    _HAS_MCP = True
except ImportError:
    _HAS_MCP = False
    # Provide a stub so the module is importable for tests even without mcp installed
    class FastMCP:  # type: ignore[no-redef]
        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self, **kwargs: Any) -> Any:  # type: ignore[override]
            def decorator(fn: Any) -> Any:
                return fn

            return decorator

        def run(self) -> None:
            raise RuntimeError("mcp package not installed. Run: pip install mcp")


from media_advisor.config import Settings

_settings = Settings()
_ROOT = _settings.root_dir.resolve()
_DB_PATH = _ROOT / ".media-advisor-index.db"

mcp = FastMCP("media-advisor")

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _get_db(db_path: Path = _DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS claims (
            id          TEXT PRIMARY KEY,
            video_id    TEXT NOT NULL,
            channel_id  TEXT NOT NULL,
            claim_text  TEXT NOT NULL,
            target_entity TEXT,
            dimension   TEXT,
            claim_type  TEXT,
            stance      TEXT,
            intensity   INTEGER,
            tags        TEXT,
            published_at TEXT,
            analyzed_at  TEXT
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
            claim_text,
            target_entity,
            dimension,
            tags,
            content='claims',
            content_rowid='rowid'
        );

        CREATE TRIGGER IF NOT EXISTS claims_ai AFTER INSERT ON claims BEGIN
            INSERT INTO claims_fts(rowid, claim_text, target_entity, dimension, tags)
            VALUES (new.rowid, new.claim_text, new.target_entity, new.dimension, new.tags);
        END;

        CREATE TRIGGER IF NOT EXISTS claims_ad AFTER DELETE ON claims BEGIN
            INSERT INTO claims_fts(claims_fts, rowid, claim_text, target_entity, dimension, tags)
            VALUES ('delete', old.rowid, old.claim_text, old.target_entity, old.dimension, old.tags);
        END;
        """
    )
    con.commit()


# ---------------------------------------------------------------------------
# Tool: index_transcripts
# ---------------------------------------------------------------------------


@mcp.tool(description="Index all analysis JSON files from analysis/ into SQLite FTS5.")
def index_transcripts(
    root: str = "",
    channel_id: str = "",
) -> dict[str, Any]:
    """Scan analysis/<channel_id>/<video_id>.json and upsert into SQLite FTS5."""
    r = Path(root).resolve() if root else _ROOT
    analysis_dir = r / "analysis"
    if not analysis_dir.exists():
        return {"ok": False, "error": f"analysis/ not found at {analysis_dir}"}

    con = _get_db()
    _ensure_schema(con)

    indexed = 0
    errors: list[str] = []

    pattern = f"{channel_id}/*/*.json" if channel_id else "*/*.json"
    for json_path in sorted(analysis_dir.glob(pattern)):
        ch_id = json_path.parent.parent.name if not channel_id else channel_id
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"{json_path}: {e}")
            continue

        video_id = data.get("video_id", json_path.stem)
        analyzed_at = data.get("analyzed_at", "")
        published_at = (data.get("metadata") or {}).get("published_at", "")
        claims = data.get("claims") or []

        for claim in claims:
            cid = claim.get("claim_id") or f"{video_id}_{claim.get('segment_id','')}"
            tags = json.dumps(claim.get("tags") or [], ensure_ascii=False)
            try:
                con.execute(
                    """
                    INSERT OR REPLACE INTO claims
                    (id, video_id, channel_id, claim_text, target_entity,
                     dimension, claim_type, stance, intensity, tags, published_at, analyzed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        video_id,
                        ch_id,
                        claim.get("claim_text") or claim.get("position") or "",
                        claim.get("target_entity") or claim.get("subject") or "",
                        claim.get("dimension") or claim.get("topic") or "",
                        claim.get("claim_type") or "",
                        claim.get("stance") or "",
                        claim.get("intensity"),
                        tags,
                        published_at,
                        analyzed_at,
                    ),
                )
                indexed += 1
            except Exception as e:
                errors.append(f"{cid}: {e}")

    con.commit()
    con.close()
    return {"ok": True, "indexed": indexed, "errors": errors[:10]}


# ---------------------------------------------------------------------------
# Tool: query
# ---------------------------------------------------------------------------


@mcp.tool(description="Full-text search across indexed claims. Returns matching claims.")
def query(
    q: str,
    channel_id: str = "",
    dimension: str = "",
    limit: int = 20,
) -> dict[str, Any]:
    """Search claims via FTS5. Optionally filter by channel_id and/or dimension."""
    if not q.strip():
        return {"ok": False, "error": "Empty query"}

    con = _get_db()
    _ensure_schema(con)

    conditions = ["claims_fts MATCH ?"]
    params: list[Any] = [q]

    if channel_id:
        conditions.append("c.channel_id = ?")
        params.append(channel_id)
    if dimension:
        conditions.append("c.dimension = ?")
        params.append(dimension)

    where = " AND ".join(conditions)
    sql = f"""
        SELECT c.id, c.video_id, c.channel_id, c.claim_text,
               c.target_entity, c.dimension, c.stance, c.intensity,
               c.tags, c.published_at
        FROM claims c
        JOIN claims_fts ON claims_fts.rowid = c.rowid
        WHERE {where}
        ORDER BY rank
        LIMIT ?
    """
    params.append(limit)

    try:
        rows = con.execute(sql, params).fetchall()
    except sqlite3.OperationalError as e:
        con.close()
        return {"ok": False, "error": str(e)}

    con.close()
    results = [dict(r) for r in rows]
    return {"ok": True, "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Tool: channel_report
# ---------------------------------------------------------------------------


@mcp.tool(description="Generate a summary report for a channel: top themes, top claims, entity breakdown.")
def channel_report(
    channel_id: str,
    limit_claims: int = 20,
) -> dict[str, Any]:
    """Aggregate all indexed claims for a channel into a structured report."""
    if not channel_id.strip():
        return {"ok": False, "error": "channel_id required"}

    con = _get_db()
    _ensure_schema(con)

    # Top dimensions
    dimensions = con.execute(
        """
        SELECT dimension, COUNT(*) AS cnt
        FROM claims
        WHERE channel_id = ?
        GROUP BY dimension
        ORDER BY cnt DESC
        """,
        (channel_id,),
    ).fetchall()

    # Top entities
    entities = con.execute(
        """
        SELECT target_entity, COUNT(*) AS cnt
        FROM claims
        WHERE channel_id = ? AND target_entity != ''
        GROUP BY target_entity
        ORDER BY cnt DESC
        LIMIT 15
        """,
        (channel_id,),
    ).fetchall()

    # Stance distribution
    stances = con.execute(
        """
        SELECT stance, COUNT(*) AS cnt
        FROM claims
        WHERE channel_id = ?
        GROUP BY stance
        ORDER BY cnt DESC
        """,
        (channel_id,),
    ).fetchall()

    # Most specific claims (high intensity)
    top_claims = con.execute(
        """
        SELECT id, video_id, claim_text, target_entity, dimension, stance, intensity, published_at
        FROM claims
        WHERE channel_id = ?
        ORDER BY intensity DESC, LENGTH(claim_text) DESC
        LIMIT ?
        """,
        (channel_id, limit_claims),
    ).fetchall()

    con.close()

    return {
        "ok": True,
        "channel_id": channel_id,
        "top_dimensions": [dict(r) for r in dimensions],
        "top_entities": [dict(r) for r in entities],
        "stance_distribution": [dict(r) for r in stances],
        "top_claims": [dict(r) for r in top_claims],
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
