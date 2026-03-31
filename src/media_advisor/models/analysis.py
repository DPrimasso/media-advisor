"""AnalysisResult — compat with src/analyzer/types.ts output shape."""

from typing import Literal

from pydantic import BaseModel, field_validator


class AnalysisClaim(BaseModel):
    """Backward-compat claim shape (topic/subject/position/polarity) + full v2 fields."""

    topic: str
    subject: str | None = None
    position: str
    polarity: Literal["positive", "negative", "neutral"] | None = None
    # v2 extended fields (optional, present when analyzed with v2 pipeline)
    claim_id: str | None = None
    video_id: str | None = None
    segment_id: str | None = None
    target_entity: str | None = None
    entity_type: str | None = None
    dimension: str | None = None
    claim_type: str | None = None
    stance: str | None = None
    intensity: int | None = None

    @field_validator("intensity", mode="before")
    @classmethod
    def coerce_intensity(cls, v: object) -> int | None:
        if v is None:
            return None
        return int(float(str(v)))
    modality: str | None = None
    claim_text: str | None = None
    evidence_quotes: list[dict] | None = None  # type: ignore[type-arg]
    tags: list[str] | None = None


class AnalysisMetadata(BaseModel):
    title: str | None = None
    author_name: str | None = None
    published_at: str | None = None


class TopicEntry(BaseModel):
    name: str
    relevance: Literal["high", "medium", "low"]


class AnalysisResult(BaseModel):
    video_id: str
    analyzed_at: str
    metadata: AnalysisMetadata | None = None
    summary: str
    topics: list[TopicEntry] = []
    claims: list[AnalysisClaim] | None = None
