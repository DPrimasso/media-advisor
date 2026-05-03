"""Import existing JSON transcripts and daily report caches into SQLite.

Usage:
  python -m media_advisor.tools.migrate_json_to_sqlite
"""

from __future__ import annotations

from media_advisor.config import Settings
from media_advisor.db.repository import (
    migrate_analysis_from_json_tree,
    migrate_channels_from_disk,
    migrate_daily_reports_from_files,
    migrate_mercato_from_disk,
    migrate_transcripts_from_json_tree,
)
from media_advisor.db.session import session_scope


def main() -> None:
    settings = Settings()
    root = settings.root_dir.resolve()
    transcripts_root = root / "data" / "transcripts"
    reports_dir = root / "reports"
    analysis_root = root / "data" / "analysis"
    with session_scope(root) as session:
        t_imp, t_err = migrate_transcripts_from_json_tree(transcripts_root, session)
        r_imp, r_err = migrate_daily_reports_from_files(reports_dir, session)
        a_imp, a_err = migrate_analysis_from_json_tree(analysis_root, session)
        m_counts = migrate_mercato_from_disk(root, session)
        ch_counts = migrate_channels_from_disk(root, session)
    print(f"transcripts: imported {t_imp}, read errors {t_err}")
    print(f"daily_reports: imported {r_imp}, read errors {r_err}")
    print(f"video_analysis: imported {a_imp}, read errors {a_err}")
    print(f"mercato: {m_counts}")
    print(f"channels: {ch_counts}")
    print(f"database: {settings.get_database_url(data_root=root)}")


if __name__ == "__main__":
    main()
