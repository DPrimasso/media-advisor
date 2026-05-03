"""CRUD for transcripts and daily reports."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from media_advisor.db.models import (
    AppStateDocRow,
    ChannelRegistryRow,
    ChannelVideoListRow,
    DailyReportRow,
    MercatoBlobRow,
    MercatoGlobalIndexRow,
    MercatoVideoResultRow,
    TranscriptRow,
    VideoAnalysisRow,
)

_PAIR_QUERY_CHUNK = 400


def _existing_ch_video_pair_keys(
    session: Session,
    channel_id_col: Any,
    video_id_col: Any,
    vid_channel_pairs: Sequence[tuple[str, str]],
) -> set[tuple[str, str]]:
    """Pairs are (video_id, channel_id); returns DB rows as (channel_id, video_id)."""
    if not vid_channel_pairs:
        return set()
    keys = [(ch_id, vid) for vid, ch_id in vid_channel_pairs]
    out: set[tuple[str, str]] = set()
    for i in range(0, len(keys), _PAIR_QUERY_CHUNK):
        chunk = keys[i : i + _PAIR_QUERY_CHUNK]
        stmt = select(channel_id_col, video_id_col).where(
            tuple_(channel_id_col, video_id_col).in_(chunk)
        )
        out.update((ch, vid) for ch, vid in session.execute(stmt))
    return out


def upsert_transcript(session: Session, channel_id: str, video_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(TranscriptRow).values(
        channel_id=channel_id,
        video_id=video_id,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["channel_id", "video_id"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_transcript_payload(session: Session, channel_id: str, video_id: str) -> dict[str, Any] | None:
    row = session.scalar(
        select(TranscriptRow).where(
            TranscriptRow.channel_id == channel_id,
            TranscriptRow.video_id == video_id,
        )
    )
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None


def transcript_exists_in_db(session: Session, channel_id: str, video_id: str) -> bool:
    return (
        session.scalar(
            select(TranscriptRow.id).where(
                TranscriptRow.channel_id == channel_id,
                TranscriptRow.video_id == video_id,
            )
        )
        is not None
    )


def transcript_existing_pair_keys(
    session: Session, vid_channel_pairs: Sequence[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Pairs are (video_id, channel_id); returns existing rows as (channel_id, video_id)."""
    return _existing_ch_video_pair_keys(
        session, TranscriptRow.channel_id, TranscriptRow.video_id, vid_channel_pairs
    )


def list_transcript_video_ids(session: Session, channel_id: str | None = None) -> list[tuple[str, str]]:
    q = select(TranscriptRow.channel_id, TranscriptRow.video_id).order_by(
        TranscriptRow.channel_id, TranscriptRow.video_id
    )
    if channel_id is not None:
        q = q.where(TranscriptRow.channel_id == channel_id)
    return list(session.execute(q).all())


def upsert_daily_report(
    session: Session,
    *,
    report_date: date,
    digest_raw: str,
    digest_items: list[dict[str, Any]],
    markdown_body: str,
    telegram_html: str,
    twitter_txt: str,
    generated_at: datetime,
) -> None:
    items_raw = json.dumps(digest_items, ensure_ascii=False)
    gen = generated_at if generated_at.tzinfo else generated_at.replace(tzinfo=UTC)
    stmt = sqlite_insert(DailyReportRow).values(
        report_date=report_date,
        digest_raw=digest_raw,
        digest_items_json=items_raw,
        markdown_body=markdown_body,
        telegram_html=telegram_html,
        twitter_txt=twitter_txt,
        generated_at=gen,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["report_date"],
        set_={
            "digest_raw": stmt.excluded.digest_raw,
            "digest_items_json": stmt.excluded.digest_items_json,
            "markdown_body": stmt.excluded.markdown_body,
            "telegram_html": stmt.excluded.telegram_html,
            "twitter_txt": stmt.excluded.twitter_txt,
            "generated_at": stmt.excluded.generated_at,
        },
    )
    session.execute(stmt)


def fetch_daily_report_cache_dict(session: Session, report_date: date) -> dict[str, Any] | None:
    row = session.get(DailyReportRow, report_date)
    if row is None:
        return None
    try:
        digest_items = json.loads(row.digest_items_json)
    except json.JSONDecodeError:
        digest_items = []
    day = report_date.isoformat()
    return {
        "digest_raw": row.digest_raw,
        "digest_items": digest_items if isinstance(digest_items, list) else [],
        "generated_at": row.generated_at.isoformat(),
        "telegram_path": f"reports/{day}.telegram.html",
        "twitter_path": f"reports/{day}.twitter.txt",
    }


def migrate_transcripts_from_json_tree(transcripts_root: Path, session: Session) -> tuple[int, int]:
    """Import data/transcripts/<channel>/<video>.json. Returns (imported, skipped_errors)."""
    imported = 0
    errors = 0
    if not transcripts_root.is_dir():
        return 0, 0
    for ch_dir in sorted(p for p in transcripts_root.iterdir() if p.is_dir()):
        if ch_dir.name.startswith("_"):
            continue
        channel_id = ch_dir.name
        for jf in sorted(ch_dir.glob("*.json")):
            video_id = jf.stem
            try:
                payload = json.loads(jf.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    errors += 1
                    continue
                upsert_transcript(session, channel_id, video_id, payload)
                imported += 1
            except (OSError, json.JSONDecodeError):
                errors += 1
    return imported, errors


def migrate_daily_reports_from_files(reports_dir: Path, session: Session) -> tuple[int, int]:
    """Import reports/YYYY-MM-DD.json (+ optional sidecar md/html/txt). Returns (imported, errors)."""
    imported = 0
    errors = 0
    if not reports_dir.is_dir():
        return 0, 0
    for cache_path in sorted(reports_dir.glob("*.json")):
        name = cache_path.stem
        try:
            report_date = date.fromisoformat(name)
        except ValueError:
            continue
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            errors += 1
            continue
        digest_raw = data.get("digest_raw") or ""
        if not digest_raw:
            errors += 1
            continue
        digest_items = data.get("digest_items") or []
        if not isinstance(digest_items, list):
            digest_items = []
        gen_s = data.get("generated_at")
        if gen_s:
            try:
                gen = datetime.fromisoformat(str(gen_s).replace("Z", "+00:00"))
            except ValueError:
                gen = datetime.now(UTC)
        else:
            gen = datetime.now(UTC)
        day = report_date.isoformat()
        md_path = reports_dir / f"{day}.md"
        tg_path = reports_dir / f"{day}.telegram.html"
        tw_path = reports_dir / f"{day}.twitter.txt"
        markdown_body = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        telegram_html = tg_path.read_text(encoding="utf-8") if tg_path.exists() else ""
        twitter_txt = tw_path.read_text(encoding="utf-8") if tw_path.exists() else ""
        upsert_daily_report(
            session,
            report_date=report_date,
            digest_raw=digest_raw,
            digest_items=digest_items,
            markdown_body=markdown_body,
            telegram_html=telegram_html,
            twitter_txt=twitter_txt,
            generated_at=gen,
        )
        imported += 1
    return imported, errors


# --- video analysis ---

def upsert_video_analysis(session: Session, channel_id: str, video_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(VideoAnalysisRow).values(
        channel_id=channel_id,
        video_id=video_id,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["channel_id", "video_id"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_video_analysis_payload(
    session: Session, channel_id: str, video_id: str
) -> dict[str, Any] | None:
    row = session.scalar(
        select(VideoAnalysisRow).where(
            VideoAnalysisRow.channel_id == channel_id,
            VideoAnalysisRow.video_id == video_id,
        )
    )
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None


def analysis_exists_in_db(session: Session, channel_id: str, video_id: str) -> bool:
    return (
        session.scalar(
            select(VideoAnalysisRow.id).where(
                VideoAnalysisRow.channel_id == channel_id,
                VideoAnalysisRow.video_id == video_id,
            )
        )
        is not None
    )


def analysis_existing_pair_keys(
    session: Session, vid_channel_pairs: Sequence[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Pairs are (video_id, channel_id); returns existing rows as (channel_id, video_id)."""
    return _existing_ch_video_pair_keys(
        session, VideoAnalysisRow.channel_id, VideoAnalysisRow.video_id, vid_channel_pairs
    )


def iter_all_video_analysis_rows(session: Session) -> list[VideoAnalysisRow]:
    return list(session.scalars(select(VideoAnalysisRow).order_by(VideoAnalysisRow.channel_id, VideoAnalysisRow.video_id)).all())


def migrate_analysis_from_json_tree(analysis_root: Path, session: Session) -> tuple[int, int]:
    imported = 0
    errors = 0
    if not analysis_root.is_dir():
        return 0, 0
    for ch_dir in sorted(p for p in analysis_root.iterdir() if p.is_dir()):
        channel_id = ch_dir.name
        for jf in sorted(ch_dir.glob("*.json")):
            if jf.name.startswith("_"):
                continue
            video_id = jf.stem
            try:
                payload = json.loads(jf.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    errors += 1
                    continue
                upsert_video_analysis(session, channel_id, video_id, payload)
                imported += 1
            except (OSError, json.JSONDecodeError):
                errors += 1
    return imported, errors


# --- mercato ---

MERCATO_INDEX_SINGLETON = 1
MERCATO_BLOB_ALIASES = "player_aliases"
MERCATO_BLOB_TRANSFERS = "transfers"
MERCATO_BLOB_TM_IDS = "player_tm_ids"

CHANNEL_REGISTRY_SINGLETON = 1
APP_DOC_PENDING = "pending"
APP_DOC_VIDEO_DATES = "video_dates"


def upsert_mercato_video_result(session: Session, channel_id: str, video_id: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(MercatoVideoResultRow).values(
        channel_id=channel_id,
        video_id=video_id,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["channel_id", "video_id"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_mercato_video_result_payload(
    session: Session, channel_id: str, video_id: str
) -> dict[str, Any] | None:
    row = session.scalar(
        select(MercatoVideoResultRow).where(
            MercatoVideoResultRow.channel_id == channel_id,
            MercatoVideoResultRow.video_id == video_id,
        )
    )
    if row is None:
        return None
    try:
        return json.loads(row.payload_json)
    except json.JSONDecodeError:
        return None


def mercato_video_result_exists(session: Session, channel_id: str, video_id: str) -> bool:
    return (
        session.scalar(
            select(MercatoVideoResultRow.id).where(
                MercatoVideoResultRow.channel_id == channel_id,
                MercatoVideoResultRow.video_id == video_id,
            )
        )
        is not None
    )


def mercato_existing_pair_keys(
    session: Session, vid_channel_pairs: Sequence[tuple[str, str]]
) -> set[tuple[str, str]]:
    """Pairs are (video_id, channel_id); returns existing rows as (channel_id, video_id)."""
    return _existing_ch_video_pair_keys(
        session, MercatoVideoResultRow.channel_id, MercatoVideoResultRow.video_id, vid_channel_pairs
    )


def list_mercato_video_result_rows(session: Session, channel_id: str | None = None) -> list[MercatoVideoResultRow]:
    q = select(MercatoVideoResultRow).order_by(MercatoVideoResultRow.channel_id, MercatoVideoResultRow.video_id)
    if channel_id is not None:
        q = q.where(MercatoVideoResultRow.channel_id == channel_id)
    return list(session.scalars(q).all())


def fetch_mercato_global_index_json(session: Session) -> str | None:
    row = session.get(MercatoGlobalIndexRow, MERCATO_INDEX_SINGLETON)
    return row.payload_json if row else None


def upsert_mercato_global_index(session: Session, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(MercatoGlobalIndexRow).values(
        singleton_id=MERCATO_INDEX_SINGLETON,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["singleton_id"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_mercato_blob_raw(session: Session, blob_key: str) -> str | None:
    row = session.get(MercatoBlobRow, blob_key)
    return row.payload_json if row else None


def upsert_mercato_blob(session: Session, blob_key: str, payload: dict[str, Any] | list[Any] | Any) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(MercatoBlobRow).values(
        blob_key=blob_key,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["blob_key"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def migrate_mercato_from_disk(root: Path, session: Session) -> dict[str, int]:
    """Import mercato/tips/**, index, and auxiliary JSON into DB. Returns per-kind counts."""
    from media_advisor.io.paths import (
        mercato_index_path,
        player_aliases_path,
        player_tm_ids_path,
        transfers_index_path,
    )

    counts: dict[str, int] = {"tips": 0, "index": 0, "aliases": 0, "transfers": 0, "tm_ids": 0}
    tips_root = root / "mercato" / "tips"
    if tips_root.is_dir():
        for ch_dir in sorted(p for p in tips_root.iterdir() if p.is_dir()):
            ch_id = ch_dir.name
            for jf in sorted(ch_dir.glob("*.json")):
                vid = jf.stem
                try:
                    payload = json.loads(jf.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        upsert_mercato_video_result(session, ch_id, vid, payload)
                        counts["tips"] += 1
                except (OSError, json.JSONDecodeError):
                    pass
    idx_path = mercato_index_path(root)
    if idx_path.exists():
        try:
            data = json.loads(idx_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                upsert_mercato_global_index(session, data)
                counts["index"] = 1
        except (OSError, json.JSONDecodeError):
            pass
    blob_files = (
        (player_aliases_path(root), MERCATO_BLOB_ALIASES, "aliases"),
        (transfers_index_path(root), MERCATO_BLOB_TRANSFERS, "transfers"),
        (player_tm_ids_path(root), MERCATO_BLOB_TM_IDS, "tm_ids"),
    )
    for path, blob_key, count_key in blob_files:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                upsert_mercato_blob(session, blob_key, data)
                counts[count_key] = 1
            except (OSError, json.JSONDecodeError):
                pass
    return counts


# --- channels ---

def fetch_channel_registry_json(session: Session) -> str | None:
    row = session.get(ChannelRegistryRow, CHANNEL_REGISTRY_SINGLETON)
    return row.payload_json if row else None


def upsert_channel_registry(session: Session, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(ChannelRegistryRow).values(
        singleton_id=CHANNEL_REGISTRY_SINGLETON,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["singleton_id"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_channel_video_list_urls_json(session: Session, list_key: str) -> str | None:
    row = session.get(ChannelVideoListRow, list_key)
    return row.urls_json if row else None


def upsert_channel_video_list(session: Session, list_key: str, urls: list[str]) -> None:
    raw = json.dumps(urls, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(ChannelVideoListRow).values(
        list_key=list_key,
        urls_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["list_key"],
        set_={
            "urls_json": stmt.excluded.urls_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def fetch_app_state_doc_json(session: Session, doc_key: str) -> str | None:
    row = session.get(AppStateDocRow, doc_key)
    return row.payload_json if row else None


def upsert_app_state_doc(session: Session, doc_key: str, payload: dict[str, Any]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    now = datetime.now(UTC)
    stmt = sqlite_insert(AppStateDocRow).values(
        doc_key=doc_key,
        payload_json=raw,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["doc_key"],
        set_={
            "payload_json": stmt.excluded.payload_json,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    session.execute(stmt)


def migrate_channels_from_disk(root: Path, session: Session) -> dict[str, int]:
    from media_advisor.io.paths import channels_config_path, pending_path, video_dates_cache_path

    counts: dict[str, int] = {"registry": 0, "lists": 0, "pending": 0, "video_dates": 0}
    reg_path = channels_config_path(root)
    if reg_path.exists():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                upsert_channel_registry(session, data)
                counts["registry"] = 1
                cfg_channels = data.get("channels") or []
                if isinstance(cfg_channels, list):
                    for ch in cfg_channels:
                        if not isinstance(ch, dict):
                            continue
                        list_file = ch.get("video_list")
                        ch_id = ch.get("id")
                        if not list_file or not ch_id:
                            continue
                        lp = root / "channels" / str(list_file)
                        if lp.exists():
                            try:
                                urls_raw = json.loads(lp.read_text(encoding="utf-8"))
                                if isinstance(urls_raw, list):
                                    upsert_channel_video_list(session, str(list_file), [str(u) for u in urls_raw])
                                    counts["lists"] += 1
                            except (OSError, json.JSONDecodeError):
                                pass
        except (OSError, json.JSONDecodeError):
            pass
    pp = pending_path(root)
    if pp.exists():
        try:
            data = json.loads(pp.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                upsert_app_state_doc(session, APP_DOC_PENDING, data)
                counts["pending"] = 1
        except (OSError, json.JSONDecodeError):
            pass
    vd = video_dates_cache_path(root)
    if vd.exists():
        try:
            data = json.loads(vd.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                upsert_app_state_doc(session, APP_DOC_VIDEO_DATES, data)
                counts["video_dates"] = 1
        except (OSError, json.JSONDecodeError):
            pass
    return counts
