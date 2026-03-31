"""Step 1B — Segmenter.

fixed_window: blocks of ~180s.
topic_shift: naive token-count split targeting max_segments per video.
Porting of src/pipeline/segmenter.ts.
"""

from dataclasses import dataclass
from typing import Literal

from media_advisor.pipeline.cleaner import CleanSegment

SegmenterMode = Literal["fixed_window", "topic_shift"]


@dataclass
class Segment:
    segment_id: str
    start_sec: float
    end_sec: float
    text: str
    token_count: int


def _count_tokens(text: str) -> int:
    return len([w for w in text.split() if w])


def _segment_fixed_window(
    items: list[CleanSegment],
    window_sec: float,
    min_window_sec: float,
) -> list[Segment]:
    segments: list[Segment] = []
    seg_idx = 0
    current_start = 0.0
    current_end = 0.0
    current_text: list[str] = []
    current_tokens = 0

    for item in items:
        item_end = item.end_sec
        item_tokens = _count_tokens(item.text)

        would_exceed = (current_end > 0 and item_end - current_start > window_sec) or (
            current_end > 0
            and item_end - current_start >= min_window_sec
            and current_tokens + item_tokens > 100
        )

        if would_exceed and current_text:
            segments.append(
                Segment(
                    segment_id=f"s{seg_idx}",
                    start_sec=current_start,
                    end_sec=current_end,
                    text=" ".join(current_text).strip(),
                    token_count=current_tokens,
                )
            )
            seg_idx += 1
            current_start = item.start_sec
            current_end = item_end
            current_text = [item.text]
            current_tokens = item_tokens
        else:
            if not current_text:
                current_start = item.start_sec
            current_end = item_end
            current_text.append(item.text)
            current_tokens += item_tokens

    if current_text:
        segments.append(
            Segment(
                segment_id=f"s{seg_idx}",
                start_sec=current_start,
                end_sec=current_end,
                text=" ".join(current_text).strip(),
                token_count=current_tokens,
            )
        )

    return segments


def _segment_topic_shift(items: list[CleanSegment], max_segments: int) -> list[Segment]:
    total_text = " ".join(x.text for x in items)
    total_tokens = _count_tokens(total_text)
    target_per_seg = max(50, -(-total_tokens // max_segments))  # ceiling div

    segments: list[Segment] = []
    seg_idx = 0
    acc_text: list[str] = []
    acc_tokens = 0
    seg_start = 0.0
    seg_end = 0.0

    for item in items:
        tokens = _count_tokens(item.text)
        would_exceed = acc_tokens + tokens > target_per_seg and bool(acc_text)

        if would_exceed and seg_idx < max_segments - 1:
            segments.append(
                Segment(
                    segment_id=f"s{seg_idx}",
                    start_sec=seg_start,
                    end_sec=seg_end,
                    text=" ".join(acc_text).strip(),
                    token_count=acc_tokens,
                )
            )
            seg_idx += 1
            acc_text = [item.text]
            acc_tokens = tokens
            seg_start = item.start_sec
            seg_end = item.end_sec
        else:
            if not acc_text:
                seg_start = item.start_sec
            acc_text.append(item.text)
            acc_tokens += tokens
            seg_end = item.end_sec

    if acc_text:
        segments.append(
            Segment(
                segment_id=f"s{seg_idx}",
                start_sec=seg_start,
                end_sec=seg_end,
                text=" ".join(acc_text).strip(),
                token_count=acc_tokens,
            )
        )

    return segments


def segment(
    clean_segments: list[CleanSegment],
    mode: SegmenterMode = "fixed_window",
    window_seconds: float = 180.0,
    min_window_seconds: float = 120.0,
    max_segments: int = 12,
) -> list[Segment]:
    if not clean_segments:
        return []
    if mode == "topic_shift":
        return _segment_topic_shift(clean_segments, max_segments)
    return _segment_fixed_window(clean_segments, window_seconds, min_window_seconds)
