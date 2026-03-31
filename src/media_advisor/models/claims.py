"""Claims schema — porting of src/schema/claims.ts."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

DimensionValue = Literal[
    "performance",
    "tactics",
    "market",
    "finance",
    "leadership",
    "injury",
    "lineup_prediction",
    "refereeing",
    "fan_behavior",
    "standings",
    "europe",
    "rivalry",
    "media",
]

ClaimTypeValue = Literal[
    "FACT",
    "OBSERVATION",
    "INTERPRETATION",
    "JUDGEMENT",
    "PRESCRIPTION",
    "PREDICTION",
    "META_INFO_QUALITY",
]

StanceValue = Literal["POS", "NEG", "NEU", "MIXED"]

ModalityValue = Literal["CERTAIN", "PROBABLE", "POSSIBLE", "HYPOTHESIS", "PRESCRIPTIVE"]

EntityTypeValue = Literal["team", "player", "coach", "ref", "club", "other"]


class EvidenceQuote(BaseModel):
    quote_text: str
    start_sec: float
    end_sec: float
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


class Claim(BaseModel):
    claim_id: str
    video_id: str
    segment_id: str
    target_entity: str
    entity_type: EntityTypeValue
    dimension: DimensionValue
    claim_type: ClaimTypeValue
    stance: StanceValue
    intensity: Literal[0, 1, 2, 3]
    modality: ModalityValue
    claim_text: str = Field(min_length=15)
    evidence_quotes: list[EvidenceQuote] = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)

    @field_validator("evidence_quotes")
    @classmethod
    def max_two_quotes(cls, v: list[EvidenceQuote]) -> list[EvidenceQuote]:
        if len(v) > 2:
            raise ValueError("Max 2 evidence_quotes")
        return v

    @field_validator("tags")
    @classmethod
    def max_six_tags(cls, v: list[str]) -> list[str]:
        if len(v) > 6:
            raise ValueError("Max 6 tags")
        return v


class Theme(BaseModel):
    theme: str
    weight: float = Field(ge=0, le=100)


class VideoAnalysis(BaseModel):
    video_id: str
    themes: list[Theme]
    claims: list[Claim]
    summary_short: str = Field(max_length=600)
    summary_long: str | None = None
