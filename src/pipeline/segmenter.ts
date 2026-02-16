/**
 * Step 1B — Segmenter.
 * fixed_window: blocks of 120-240s (config)
 * topic_shift: semantic segmentation with max ~12 segments/video (naive sentence-split for now)
 */

import type { CleanSegment } from "./transcript-cleaner.js";

export interface Segment {
  segment_id: string;
  start_sec: number;
  end_sec: number;
  text: string;
  token_count: number;
}

export type SegmenterMode = "fixed_window" | "topic_shift";

export interface SegmenterConfig {
  mode: SegmenterMode;
  /** fixed_window: target duration in seconds */
  window_seconds?: number;
  /** fixed_window: min overlap to avoid cutting mid-sentence */
  min_window_seconds?: number;
  /** topic_shift: max segments per video */
  max_segments?: number;
}

const DEFAULT_FIXED: SegmenterConfig = {
  mode: "fixed_window",
  window_seconds: 180,
  min_window_seconds: 120,
};

const DEFAULT_TOPIC: SegmenterConfig = {
  mode: "topic_shift",
  max_segments: 12,
};

function countTokens(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

function segmentFixedWindow(
  items: CleanSegment[],
  windowSec: number,
  minWindowSec: number
): Segment[] {
  const segments: Segment[] = [];
  let segIdx = 0;
  let currentStart = 0;
  let currentEnd = 0;
  let currentText: string[] = [];
  let currentTokens = 0;

  for (const item of items) {
    const itemEnd = item.end_sec;
    const itemTokens = countTokens(item.text);

    const wouldExceed = (currentEnd > 0 && itemEnd - currentStart > windowSec) ||
      (currentEnd > 0 && itemEnd - currentStart >= minWindowSec && currentTokens + itemTokens > 100);

    if (wouldExceed && currentText.length > 0) {
      segments.push({
        segment_id: `s${segIdx}`,
        start_sec: currentStart,
        end_sec: currentEnd,
        text: currentText.join(" ").trim(),
        token_count: currentTokens,
      });
      segIdx++;
      currentStart = item.start_sec;
      currentEnd = item.end_sec;
      currentText = [item.text];
      currentTokens = itemTokens;
    } else {
      if (currentText.length === 0) currentStart = item.start_sec;
      currentEnd = item.end_sec;
      currentText.push(item.text);
      currentTokens += itemTokens;
    }
  }

  if (currentText.length > 0) {
    segments.push({
      segment_id: `s${segIdx}`,
      start_sec: currentStart,
      end_sec: currentEnd,
      text: currentText.join(" ").trim(),
      token_count: currentTokens,
    });
  }

  return segments;
}

/** topic_shift: naive implementation — split by chunk size to hit max_segments */
function segmentTopicShift(
  items: CleanSegment[],
  maxSegments: number
): Segment[] {
  const totalText = items.map((x) => x.text).join(" ");
  const totalTokens = countTokens(totalText);
  const targetPerSeg = Math.max(50, Math.ceil(totalTokens / maxSegments));

  const segments: Segment[] = [];
  let segIdx = 0;
  let accText: string[] = [];
  let accTokens = 0;
  let segStart = 0;
  let segEnd = 0;

  for (const item of items) {
    const tokens = countTokens(item.text);
    const wouldExceed = accTokens + tokens > targetPerSeg && accText.length > 0;

    if (wouldExceed && segIdx < maxSegments - 1) {
      segments.push({
        segment_id: `s${segIdx}`,
        start_sec: segStart,
        end_sec: segEnd,
        text: accText.join(" ").trim(),
        token_count: accTokens,
      });
      segIdx++;
      accText = [item.text];
      accTokens = tokens;
      segStart = item.start_sec;
      segEnd = item.end_sec;
    } else {
      if (accText.length === 0) segStart = item.start_sec;
      accText.push(item.text);
      accTokens += tokens;
      segEnd = item.end_sec;
    }
  }

  if (accText.length > 0) {
    segments.push({
      segment_id: `s${segIdx}`,
      start_sec: segStart,
      end_sec: segEnd,
      text: accText.join(" ").trim(),
      token_count: accTokens,
    });
  }

  return segments;
}

export function segment(
  cleanSegments: CleanSegment[],
  config: Partial<SegmenterConfig> = {}
): Segment[] {
  const cfg = config.mode === "topic_shift"
    ? { ...DEFAULT_TOPIC, ...config }
    : { ...DEFAULT_FIXED, ...config };

  if (cleanSegments.length === 0) return [];

  if (cfg.mode === "fixed_window") {
    return segmentFixedWindow(
      cleanSegments,
      cfg.window_seconds ?? 180,
      cfg.min_window_seconds ?? 120
    );
  }

  return segmentTopicShift(
    cleanSegments,
    cfg.max_segments ?? 12
  );
}
