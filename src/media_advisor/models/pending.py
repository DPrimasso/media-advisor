"""Pending video models — mirrors channels/pending.json shape."""

from datetime import datetime

from pydantic import BaseModel


class PendingVideo(BaseModel):
    video_id: str
    title: str
    channel_id: str
    channel_name: str
    url: str
    published_at: str | None = None


class PendingResult(BaseModel):
    fetched_at: datetime | None = None
    items: list[PendingVideo] = []
