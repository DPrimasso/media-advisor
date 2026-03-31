"""Transcript models — mirrors TranscriptAPI.com response shape."""

from pydantic import BaseModel


class TranscriptSegment(BaseModel):
    text: str
    start: float | None = None
    duration: float | None = None


class VideoMetadata(BaseModel):
    title: str = ""
    author_name: str = ""
    author_url: str = ""
    thumbnail_url: str = ""
    published_at: str | None = None


class TranscriptResponse(BaseModel):
    video_id: str
    language: str = ""
    transcript: list[TranscriptSegment] | str
    metadata: VideoMetadata | None = None
