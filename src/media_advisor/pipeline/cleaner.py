"""Step 1A — Transcript cleaning.

Removes intro/outro/sponsor segments, merges short lines, preserves timestamps.
Porting of src/pipeline/transcript-cleaner.ts.
"""

import re
from dataclasses import dataclass

from media_advisor.models.transcript import TranscriptResponse, TranscriptSegment

INTRO_OUTRO_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(iscriviti|iscrivetevi|subscribe)\b", re.IGNORECASE),
    re.compile(r"\b(like\s+al\s+video|metti\s+like|like\s+e\s+condividi)\b", re.IGNORECASE),
    re.compile(r"\b(campanellina|campanella|notifiche)\b", re.IGNORECASE),
    re.compile(r"\b(sponsor|sponsorizzato|in collaborazione con)\b", re.IGNORECASE),
    re.compile(r"\b(codice\s+sconto|sconto\s+\d+%|link\s+in\s+descrizione)\b", re.IGNORECASE),
    re.compile(
        r"\b(grazie\s+per\s+la\s+visione|ci\s+vediamo\s+al\s+prossimo|alla\s+prossima)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(amici\s+bellini|amici\s+benvenuti|benvenuti\s+in)\b", re.IGNORECASE),
    re.compile(r"\b(rumori|noise|\[.*?\])\b", re.IGNORECASE),
    re.compile(r"\b(state\s+inondando|messaggi\s+privati)\b", re.IGNORECASE),
    re.compile(r"^>>\s+"),
    re.compile(r"^\s*\.{3}\s*$"),
]

SHORT_LINE_MIN_CHARS = 15
MIN_CHARS_PER_SEGMENT = 40


@dataclass
class CleanSegment:
    start_sec: float
    end_sec: float
    text: str


def _should_drop(text: str, patterns: list[re.Pattern[str]]) -> bool:
    t = text.strip()
    if len(t) < 5:
        return True
    return any(p.search(t) for p in patterns)


def _to_clean_segments(segments: list[TranscriptSegment]) -> list[CleanSegment]:
    items: list[CleanSegment] = []
    for s in segments:
        start = s.start or 0.0
        dur = s.duration or 0.0
        items.append(CleanSegment(start_sec=start, end_sec=start + dur, text=s.text.strip()))
    return items


def clean_transcript(
    data: TranscriptResponse,
    min_chars_per_segment: int = MIN_CHARS_PER_SEGMENT,
    max_chars_per_segment: int = 500,
    drop_patterns: list[re.Pattern[str]] | None = None,
) -> list[CleanSegment]:
    patterns = drop_patterns if drop_patterns is not None else INTRO_OUTRO_PATTERNS

    if isinstance(data.transcript, str):
        raw = [CleanSegment(start_sec=0.0, end_sec=0.0, text=data.transcript.strip())]
    else:
        raw = _to_clean_segments(data.transcript)

    if not raw:
        return []

    items = [x for x in raw if not _should_drop(x.text, patterns)]

    merged: list[CleanSegment] = []
    acc: CleanSegment | None = None

    for item in items:
        if not item.text:
            continue
        combined = f"{acc.text} {item.text}" if acc else item.text

        if acc and len(combined) <= max_chars_per_segment:
            acc = CleanSegment(acc.start_sec, item.end_sec, combined)
        elif acc and len(acc.text) >= min_chars_per_segment:
            merged.append(acc)
            acc = item if len(item.text) < min_chars_per_segment else None
            if acc is None and len(item.text) >= min_chars_per_segment:
                merged.append(item)
        elif len(item.text) >= min_chars_per_segment:
            if acc:
                merged.append(acc)
            merged.append(item)
            acc = None
        else:
            acc = CleanSegment(acc.start_sec if acc else item.start_sec, item.end_sec, combined)

    if acc:
        merged.append(acc)

    return merged
