"""SQLAlchemy models for local SQLite storage."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TranscriptRow(Base):
    __tablename__ = "transcripts"
    __table_args__ = (UniqueConstraint("channel_id", "video_id", name="uq_transcript_channel_video"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DailyReportRow(Base):
    __tablename__ = "daily_reports"

    report_date: Mapped[date] = mapped_column(Date, primary_key=True)
    digest_raw: Mapped[str] = mapped_column(Text, nullable=False)
    digest_items_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    markdown_body: Mapped[str] = mapped_column(Text, nullable=False)
    telegram_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    twitter_txt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class VideoAnalysisRow(Base):
    __tablename__ = "video_analysis"
    __table_args__ = (UniqueConstraint("channel_id", "video_id", name="uq_analysis_channel_video"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MercatoVideoResultRow(Base):
    __tablename__ = "mercato_video_results"
    __table_args__ = (UniqueConstraint("channel_id", "video_id", name="uq_mercato_vid_ch"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    video_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MercatoGlobalIndexRow(Base):
    """Single row (singleton_id=1) holding serialized MercatoIndex."""

    __tablename__ = "mercato_global_index"

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MercatoBlobRow(Base):
    """Key-value JSON blobs: player_aliases, transfers, player_tm_ids."""

    __tablename__ = "mercato_blobs"

    blob_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelRegistryRow(Base):
    """Single row: full channels.json payload."""

    __tablename__ = "channel_registry"

    singleton_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChannelVideoListRow(Base):
    """Per-list-file video URL arrays (same keys as channels/*.json list filenames)."""

    __tablename__ = "channel_video_lists"

    list_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    urls_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppStateDocRow(Base):
    """pending.json and video-dates.json equivalents."""

    __tablename__ = "app_state_docs"

    doc_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
