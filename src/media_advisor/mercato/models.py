"""Modelli Pydantic per il modulo calciomercato."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


TransferType = Literal["loan", "permanent", "free_agent", "extension", "unknown"]
ConfidenceLevel = Literal["rumor", "likely", "confirmed", "denied"]
OutcomeValue = Literal["non_verificata", "confermata", "parziale", "smentita"]
OutcomeSource = Literal["manual", "transfermarkt", "auto"]

# Mapping per compatibilità backward con JSON creati prima della migrazione
_OUTCOME_MIGRATION: dict[str, OutcomeValue] = {
    "pending": "non_verificata",
    "true": "confermata",
    "false": "smentita",
    "partial": "parziale",
}


class MercatoTip(BaseModel):
    tip_id: str                          # UUID
    video_id: str
    channel_id: str
    mentioned_at: datetime | None = None  # published_at del video (None = data sconosciuta)
    extracted_at: datetime

    # Il rumor
    player_name: str                     # normalizzato via entity_normalizer
    from_club: str | None = None
    to_club: str | None = None
    transfer_type: TransferType = "unknown"
    confidence: ConfidenceLevel = "rumor"

    tip_text: str                        # sintesi max 30 parole
    quote_text: str                      # verbatim dal transcript
    quote_start_sec: float | None = None
    quote_end_sec: float | None = None

    # Outcome
    outcome: OutcomeValue = "non_verificata"
    outcome_updated_at: datetime | None = None
    outcome_notes: str | None = None
    outcome_source: OutcomeSource = "manual"

    # Corroborazione semi-auto
    corroborated_by: list[str] = Field(default_factory=list)  # video_ids
    corroboration_score: float = 0.0     # 0-1

    @field_validator("outcome", mode="before")
    @classmethod
    def migrate_outcome(cls, v: object) -> object:
        """Converte i vecchi valori di outcome (pending/true/false/partial) nei nuovi."""
        if isinstance(v, str):
            return _OUTCOME_MIGRATION.get(v, v)
        return v


class VideoMercatoResult(BaseModel):
    """Output per un singolo video: lista di tip estratte."""
    video_id: str
    channel_id: str
    extracted_at: datetime
    video_title: str | None = None
    video_published_at: datetime | None = None
    tips: list[MercatoTip] = Field(default_factory=list)


class MercatoIndex(BaseModel):
    """Indice globale di tutte le tip, per lookup rapido."""
    updated_at: datetime
    tips: list[MercatoTip] = Field(default_factory=list)


class ChannelVeracityStats(BaseModel):
    channel_id: str
    total_tips: int
    resolved_tips: int   # outcome != "pending"
    true_tips: int
    false_tips: int
    partial_tips: int
    veracity_score: float | None  # None se nessuna tip risolta


class PlayerSummary(BaseModel):
    player_name: str
    player_slug: str
    total_tips: int
    pending_tips: int
    true_tips: int
    false_tips: int
    partial_tips: int
    channels_mentioned: list[str]
    latest_mention: datetime | None = None
    tips: list[MercatoTip] = Field(default_factory=list)
