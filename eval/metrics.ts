/**
 * Step 7 — Eval metrics.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { Claim } from "../src/schema/claims.js";

const EVAL_DIR = join(process.cwd(), "eval");
const GOLD_DIR = join(EVAL_DIR, "human_gold");
const OUT_BASELINE = join(EVAL_DIR, "out_baseline");

export interface GoldClaim {
  claim_text: string;
  target_entity: string;
  evidence_quotes: Array<{ quote_text: string; start_sec: number; end_sec: number }>;
}

export interface GoldFile {
  video_id: string;
  themes: string[];
  claims: GoldClaim[];
}

function similarity(a: string, b: string): number {
  const ta = new Set(a.toLowerCase().split(/\s+/).filter((w) => w.length > 2));
  const tb = new Set(b.toLowerCase().split(/\s+/).filter((w) => w.length > 2));
  if (ta.size === 0 || tb.size === 0) return 0;
  let inter = 0;
  for (const w of ta) if (tb.has(w)) inter++;
  return inter / Math.max(ta.size, tb.size);
}

/** % claims with at least one evidence quote */
export function quoteSupportRate(claims: Array<{ evidence_quotes?: unknown[] }>): number {
  if (claims.length === 0) return 0;
  const withQuote = claims.filter((c) => (c.evidence_quotes?.length ?? 0) > 0).length;
  return withQuote / claims.length;
}

/** % duplicate/redundant claims (cosine-like similarity > 0.7) */
export function redundancyRate(claims: Array<{ claim_text?: string; position?: string }>): number {
  if (claims.length < 2) return 0;
  let pairs = 0;
  let redundant = 0;
  for (let i = 0; i < claims.length; i++) {
    for (let j = i + 1; j < claims.length; j++) {
      const t1 = claims[i].claim_text ?? claims[i].position ?? "";
      const t2 = claims[j].claim_text ?? claims[j].position ?? "";
      pairs++;
      if (similarity(t1, t2) > 0.7) redundant++;
    }
  }
  return pairs ? redundant / pairs : 0;
}

/** Heuristic: entities + numbers + length */
export function avgClaimSpecificity(claims: Claim[]): number {
  if (claims.length === 0) return 0;
  let sum = 0;
  for (const c of claims) {
    let s = 0;
    const t = (c.claim_text ?? "") + " " + (c.target_entity ?? "");
    if (/\d+/.test(t)) s += 2;
    if (/\b(pressare|rotazione|5-3-2|modulo)\b/i.test(t)) s += 2;
    if (c.target_entity?.length) s += 1;
    const wc = (c.claim_text ?? "").split(/\s+/).length;
    if (wc >= 8) s += 1;
    sum += s;
  }
  return sum / claims.length;
}

function toThemeStrings(arr: unknown[]): string[] {
  return arr
    .slice(0, 6)
    .map((t) => (typeof t === "string" ? t : (t as { theme?: string; name?: string })?.theme ?? (t as { theme?: string; name?: string })?.name ?? ""))
    .filter((s) => s && typeof s === "string");
}

/** Overlap of top 6 themes with gold */
export function coverageThemesAt6(predThemes: unknown[], goldThemes: unknown[]): number {
  const pred = new Set(toThemeStrings(Array.isArray(predThemes) ? predThemes : []).map((t) => t.toLowerCase()));
  const gold = new Set(toThemeStrings(Array.isArray(goldThemes) ? goldThemes : []).map((t) => t.toLowerCase()));
  if (gold.size === 0) return 1;
  let match = 0;
  for (const g of gold) if (pred.has(g)) match++;
  return match / gold.size;
}

/** F1 of claim matching (semantic similarity threshold) */
export function claimsF1(
  predClaims: Array<{ claim_text?: string; position?: string }>,
  goldClaims: GoldClaim[],
  threshold = 0.5
): { precision: number; recall: number; f1: number } {
  if (goldClaims.length === 0) return { precision: 1, recall: 1, f1: 1 };
  if (predClaims.length === 0) return { precision: 0, recall: 0, f1: 0 };

  const predTexts = predClaims.map((c) => c.claim_text ?? c.position ?? "");
  const goldTexts = goldClaims.map((c) => c.claim_text ?? "");

  let tp = 0;
  for (const g of goldTexts) {
    const best = Math.max(...predTexts.map((p) => similarity(p, g)));
    if (best >= threshold) tp++;
  }

  let fp = 0;
  for (const p of predTexts) {
    const best = Math.max(...goldTexts.map((g) => similarity(p, g)));
    if (best < threshold) fp++;
  }

  const precision = predClaims.length ? tp / (tp + fp) || 0 : 0;
  const recall = goldClaims.length ? tp / goldClaims.length : 0;
  const f1 = precision + recall > 0 ? (2 * precision * recall) / (precision + recall) : 0;

  return { precision, recall, f1 };
}

export async function loadGold(videoId: string): Promise<GoldFile | null> {
  try {
    const raw = await readFile(join(GOLD_DIR, `${videoId}.gold.json`), "utf-8");
    return JSON.parse(raw) as GoldFile;
  } catch {
    return null;
  }
}

export async function loadBaselineOutput(
  channelId: string,
  videoId: string
): Promise<{ summary?: string; topics?: { name: string }[]; claims?: { position?: string; subject?: string }[] } | null> {
  try {
    const raw = await readFile(join(OUT_BASELINE, channelId, `${videoId}.json`), "utf-8");
    return JSON.parse(raw);
  } catch {
    return null;
  }
}
