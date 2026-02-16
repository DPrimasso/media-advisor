/**
 * Step 1A — Transcript cleaning.
 * Removes intro/outro/sponsor, merges short lines, preserves timestamps.
 */

import type { TranscriptResponse } from "../transcript-client.js";

export interface CleanSegment {
  start_sec: number;
  end_sec: number;
  text: string;
}

const INTRO_OUTRO_PATTERNS = [
  /\b(iscriviti|iscrivetevi|subscribe)\b/i,
  /\b(like\s+al\s+video|metti\s+like|like\s+e\s+condividi)\b/i,
  /\b(campanellina|campanella|notifiche)\b/i,
  /\b(sponsor|sponsorizzato|in collaborazione con)\b/i,
  /\b(codice\s+sconto|sconto\s+\d+%|link\s+in\s+descrizione)\b/i,
  /\b(grazie\s+per\s+la\s+visione|ci\s+vediamo\s+al\s+prossimo|alla\s+prossima)\b/i,
  /\b(amici\s+bellini|amici\s+benvenuti|benvenuti\s+in)\b/i,
  /\b(rumori|noise|\[.*?\])\b/i,
  /\b(state\s+inondando|messaggi\s+privati)\b/i,
  /^>>\s+/,
  /^\s*\.{3}\s*$/,
];

const SHORT_LINE_MIN_CHARS = 15;
const MIN_CHARS_PER_SEGMENT = 40;

export interface TranscriptCleanerConfig {
  /** Min chars to keep a segment standalone (otherwise merge with next) */
  minCharsPerSegment?: number;
  /** Max chars per merged segment */
  maxCharsPerSegment?: number;
  /** Drop segments matching these patterns */
  dropPatterns?: RegExp[];
}

const DEFAULT_CONFIG: Required<TranscriptCleanerConfig> = {
  minCharsPerSegment: MIN_CHARS_PER_SEGMENT,
  maxCharsPerSegment: 500,
  dropPatterns: INTRO_OUTRO_PATTERNS,
};

function shouldDrop(text: string, patterns: RegExp[]): boolean {
  const t = text.trim();
  if (t.length < 5) return true;
  for (const p of patterns) {
    if (p.test(t)) return true;
  }
  return false;
}

function toSegments(transcript: Array<{ text: string; start?: number; duration?: number }>): CleanSegment[] {
  const items: CleanSegment[] = [];
  for (let i = 0; i < transcript.length; i++) {
    const s = transcript[i];
    const start = typeof s.start === "number" ? s.start : 0;
    const dur = typeof s.duration === "number" ? s.duration : 0;
    const end = start + dur;
    items.push({ start_sec: start, end_sec: end, text: s.text.trim() });
  }
  return items;
}

export function cleanTranscript(
  data: TranscriptResponse,
  config: TranscriptCleanerConfig = {}
): CleanSegment[] {
  const cfg = { ...DEFAULT_CONFIG, ...config };
  const raw = typeof data.transcript === "string"
    ? [{ text: data.transcript, start: 0, duration: 0 }]
    : data.transcript;

  if (!raw?.length) return [];

  let items = toSegments(raw);

  // Drop intro/outro/sponsor
  items = items.filter((x) => !shouldDrop(x.text, cfg.dropPatterns));

  // Merge short segments
  const merged: CleanSegment[] = [];
  let acc: CleanSegment | null = null;

  for (const item of items) {
    if (!item.text) continue;

    const combined: string = acc ? `${acc.text} ${item.text}` : item.text;

    if (acc && combined.length <= cfg.maxCharsPerSegment) {
      acc = { start_sec: acc.start_sec, end_sec: item.end_sec, text: combined };
    } else if (acc && acc.text.length >= cfg.minCharsPerSegment) {
      merged.push(acc);
      acc = item.text.length < cfg.minCharsPerSegment ? item : null;
      if (acc === null && item.text.length >= cfg.minCharsPerSegment) merged.push(item);
    } else if (item.text.length >= cfg.minCharsPerSegment) {
      if (acc) merged.push(acc);
      merged.push(item);
      acc = null;
    } else {
      acc = acc
        ? { start_sec: acc.start_sec, end_sec: item.end_sec, text: combined }
        : item;
    }
  }
  if (acc) merged.push(acc);

  return merged;
}
