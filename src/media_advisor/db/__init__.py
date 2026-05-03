"""SQLite persistence for transcripts and daily mercato reports."""

from media_advisor.db.engine import get_engine
from media_advisor.db.models import Base, DailyReportRow, TranscriptRow
from media_advisor.db.repository import (
    fetch_daily_report_cache_dict,
    fetch_transcript_payload,
    migrate_daily_reports_from_files,
    migrate_transcripts_from_json_tree,
    transcript_exists_in_db,
    upsert_daily_report,
    upsert_transcript,
)
from media_advisor.db.session import session_scope

__all__ = [
    "Base",
    "DailyReportRow",
    "TranscriptRow",
    "fetch_daily_report_cache_dict",
    "fetch_transcript_payload",
    "get_engine",
    "migrate_daily_reports_from_files",
    "migrate_transcripts_from_json_tree",
    "session_scope",
    "transcript_exists_in_db",
    "upsert_daily_report",
    "upsert_transcript",
]
