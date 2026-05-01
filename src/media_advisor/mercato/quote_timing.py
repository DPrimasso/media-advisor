"""Allinea quote_text dei MercatoTip ai timestamp reali del transcript salvato."""

from __future__ import annotations

import math
import re
from pathlib import Path

from media_advisor.io.json_io import read_json
from media_advisor.io.paths import transcript_path
from media_advisor.mercato.models import MercatoTip
from media_advisor.models.transcript import TranscriptResponse, TranscriptSegment


def _join_transcript_like_mercato(segments: list[TranscriptSegment]) -> str:
    return " ".join(seg.text for seg in segments if seg.text)


def _build_char_spans(segments: list[TranscriptSegment]) -> list[tuple[int, int, float | None, float | None]]:
    """Intervalli caratteri [cs, ce) nel testo flat, con start/end tempo stimato per segmento."""
    spans: list[tuple[int, int, float | None, float | None]] = []
    cursor = 0
    first_piece = True
    for seg in segments:
        if not seg.text:
            continue
        if not first_piece:
            cursor += 1
        first_piece = False
        cs = cursor
        ce = cursor + len(seg.text)
        st = float(seg.start) if seg.start is not None else None
        et: float | None
        if st is not None and seg.duration is not None:
            et = st + float(seg.duration)
        elif st is not None:
            et = st
        else:
            et = None
        spans.append((cs, ce, st, et))
        cursor = ce
    return spans


def _video_end_sec(segments: list[TranscriptSegment]) -> float | None:
    best: float | None = None
    for seg in segments:
        if seg.start is None:
            continue
        st = float(seg.start)
        if seg.duration is not None:
            end = st + float(seg.duration)
        else:
            end = st
        best = end if best is None else max(best, end)
    return best


def _find_quote_char_span(full: str, quote: str) -> tuple[int, int] | None:
    if not quote or not full:
        return None
    q = quote.strip()
    if not q:
        return None
    if q in full:
        i = full.index(q)
        return i, i + len(q)
    parts = [p for p in q.split() if p]
    if len(parts) < 2:
        return None
    pat = r"\s+".join(re.escape(p) for p in parts)
    m = re.search(pat, full)
    if m:
        return m.start(), m.end()
    m = re.search(pat, full, re.IGNORECASE)
    if m:
        return m.start(), m.end()
    # fallback: prime ~24 parole (quote LLM a volte tronca)
    if len(parts) > 24:
        short = " ".join(parts[:24])
        return _find_quote_char_span(full, short)
    return None


def times_for_char_span(
    spans: list[tuple[int, int, float | None, float | None]],
    cs: int,
    ce: int,
) -> tuple[float | None, float | None]:
    stimes: list[float] = []
    etimes: list[float] = []
    for a, b, st, et in spans:
        if b <= cs or a >= ce:
            continue
        if st is not None:
            stimes.append(st)
        if et is not None:
            etimes.append(et)
    if not stimes:
        return None, None
    start_sec = min(stimes)
    end_sec = max(etimes) if etimes else start_sec
    return start_sec, end_sec


def align_quote_to_transcript_segments(
    segments: list[TranscriptSegment],
    quote_text: str,
) -> tuple[float | None, float | None]:
    full = _join_transcript_like_mercato(segments)
    span = _find_quote_char_span(full, quote_text)
    if span is None:
        return None, None
    cs, ce = span
    char_spans = _build_char_spans(segments)
    return times_for_char_span(char_spans, cs, ce)


def clamp_start_to_video(
    start_sec: float | None,
    video_end: float | None,
) -> float | None:
    if start_sec is None:
        return None
    if math.isnan(start_sec):
        return None
    s = max(0.0, float(start_sec))
    if video_end is not None and video_end > 0:
        if s > video_end + 1.0:
            return None
        s = min(s, max(0.0, video_end - 0.5))
    return s


def try_align_mercato_tip(
    root: Path,
    tip: MercatoTip,
) -> tuple[float | None, float | None]:
    path = transcript_path(root, tip.channel_id, tip.video_id)
    if not path.exists():
        return None, None
    try:
        raw = read_json(path)
        data = TranscriptResponse.model_validate(raw)
    except Exception:
        return None, None
    if not isinstance(data.transcript, list) or not data.transcript:
        return None, None
    segs = list(data.transcript)
    st, en = align_quote_to_transcript_segments(segs, tip.quote_text or "")
    end_video = _video_end_sec(segs)
    st = clamp_start_to_video(st, end_video)
    if en is not None and end_video is not None:
        en = min(float(en), end_video)
    return st, en


def refined_start_sec_for_digest(
    root: Path,
    tip: MercatoTip,
) -> tuple[float | None, str]:
    """Ritorna (secondi per deep link, provenienza: aligned|model|none)."""
    aligned, _ = try_align_mercato_tip(root, tip)
    if aligned is not None:
        return aligned, "aligned"
    qs = tip.quote_start_sec
    if qs is None:
        return None, "none"
    try:
        qf = float(qs)
    except (TypeError, ValueError):
        return None, "none"
    if math.isnan(qf):
        return None, "none"
    path = transcript_path(root, tip.channel_id, tip.video_id)
    if path.exists():
        try:
            raw = read_json(path)
            data = TranscriptResponse.model_validate(raw)
            if isinstance(data.transcript, list):
                segs = list(data.transcript)
                end_v = _video_end_sec(segs)
                qf = clamp_start_to_video(qf, end_v)
                if qf is None:
                    return None, "none"
        except Exception:
            pass
    return qf, "model"
