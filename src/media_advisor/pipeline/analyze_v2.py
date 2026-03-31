"""V2 single-video analyzer: transcript → clean → segment → extract → aggregate → filter.

Porting of src/analyze-v2.ts.
Output shape is compat with AnalysisResult (src/analyzer/types.ts).
"""

import re
from datetime import datetime, timezone
from typing import Any

from media_advisor.models.analysis import (
    AnalysisClaim,
    AnalysisMetadata,
    AnalysisResult,
    TopicEntry,
)
from media_advisor.models.claims import Claim, Theme
from media_advisor.models.transcript import TranscriptResponse
from media_advisor.pipeline.aggregator import aggregate_video_claims
from media_advisor.pipeline.cleaner import clean_transcript
from media_advisor.pipeline.entity_normalizer import normalize_entity
from media_advisor.pipeline.extractor import extract_claims_from_segment
from media_advisor.pipeline.segmenter import segment
from media_advisor.pipeline.specificity import filter_by_specificity
from media_advisor.pipeline.summarizer import generate_summary

_META_CLAIM = re.compile(
    r"\b(appassionato|l'opinionista|l'autore|si chiama|è un commentatore|"
    r"parla di calcio|è il canale|è il creatore|vuole rispondere|"
    r"risponde ai fan|risponde alle domande)\b",
    re.IGNORECASE,
)
_META_ENTITY = re.compile(
    r"^(opinionista|autore|commentatore|valerio fluido|valerio|creator|host)$",
    re.IGNORECASE,
)
_MISATTRIBUTED_ENTITY = re.compile(r"^de bru[yi]n[e]?$", re.IGNORECASE)
_MISATTRIBUTED_VERB = re.compile(
    r"\b(ha commentato|commenta(ndo)?|ha dichiarato|ha detto|ha parlato di|ha espresso)\b",
    re.IGNORECASE,
)


def _stance_to_polarity(stance: str) -> str:
    if stance == "POS":
        return "positive"
    if stance == "NEG":
        return "negative"
    return "neutral"


def _rank_to_relevance(rank: int) -> str:
    if rank <= 2:
        return "high"
    if rank <= 5:
        return "medium"
    return "low"


def _to_compat_claim(claim: Claim) -> AnalysisClaim:
    return AnalysisClaim(
        topic=claim.dimension,
        subject=claim.target_entity or None,
        position=claim.claim_text,
        polarity=_stance_to_polarity(claim.stance),  # type: ignore[arg-type]
        claim_id=claim.claim_id,
        video_id=claim.video_id,
        segment_id=claim.segment_id,
        target_entity=claim.target_entity,
        entity_type=claim.entity_type,
        dimension=claim.dimension,
        claim_type=claim.claim_type,
        stance=claim.stance,
        intensity=claim.intensity,
        modality=claim.modality,
        claim_text=claim.claim_text,
        evidence_quotes=[q.model_dump() for q in claim.evidence_quotes],
        tags=claim.tags,
    )


def _is_valid_claim(c: Claim) -> bool:
    text = c.claim_text
    entity = c.target_entity or ""
    if _META_CLAIM.search(text):
        return False
    if _META_ENTITY.match(entity):
        return False
    if _MISATTRIBUTED_ENTITY.match(entity) and _MISATTRIBUTED_VERB.search(text):
        return False
    return True


async def analyze_video_v2(
    data: TranscriptResponse,
    video_id: str,
    channel_id: str,
    api_key: str,
    model: str = "gpt-4o-mini",
    metadata: dict[str, Any] | None = None,
    max_segments: int = 12,
    max_claims: int = 12,
) -> AnalysisResult:
    if not data.transcript or (isinstance(data.transcript, list) and not data.transcript):
        raise ValueError("Empty transcript")

    clean = clean_transcript(data)
    segments = segment(clean, mode="topic_shift", max_segments=max_segments)

    all_claims: list[Claim] = []
    all_themes: list[Theme] = []
    meta = metadata or {}

    for seg in segments:
        claims, themes = await extract_claims_from_segment(
            segment=seg,
            video_id=video_id,
            api_key=api_key,
            model=model,
            context={
                "title": meta.get("title") or (data.metadata.title if data.metadata else None),
                "published_at": meta.get("published_at")
                or (data.metadata.published_at if data.metadata else None),
                "opinionist": channel_id,
            },
        )
        for c in claims:
            c_norm = c.model_copy(update={"target_entity": normalize_entity(c.target_entity)})
            all_claims.append(c_norm)
        all_themes.extend(themes)

    filtered = [c for c in filter_by_specificity(all_claims) if _is_valid_claim(c)]

    full_text = " ".join(seg.text for seg in clean)
    summary_short = await generate_summary(
        api_key=api_key,
        model=model,
        title=meta.get("title") or (data.metadata.title if data.metadata else None),
        author=(data.metadata.author_name if data.metadata else None) or channel_id,
        full_text=full_text,
        claims=filtered,
    )

    analysis = aggregate_video_claims(
        filtered, all_themes, video_id, summary_short, max_claims=max_claims
    )

    return AnalysisResult(
        video_id=video_id,
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        metadata=AnalysisMetadata(
            title=data.metadata.title if data.metadata else None,
            author_name=data.metadata.author_name if data.metadata else None,
            published_at=data.metadata.published_at if data.metadata else None,
        )
        if data.metadata
        else None,
        summary=analysis.summary_short,
        topics=[
            TopicEntry(name=t.theme, relevance=_rank_to_relevance(i))  # type: ignore[arg-type]
            for i, t in enumerate(analysis.themes)
        ],
        claims=[_to_compat_claim(c) for c in analysis.claims],
    )
