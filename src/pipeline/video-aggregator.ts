/**
 * Step 2C — Merge claims at video level.
 * Semantic dedup, rank, max 12 claims, themes aggregated.
 */

import type { Claim, Theme, VideoAnalysis } from "../schema/claims.js";

/** Simple text similarity (Jaccard-like) for dedup when no embeddings. */
function similarity(a: string, b: string): number {
  const ta = new Set(a.toLowerCase().split(/\s+/).filter((w) => w.length > 2));
  const tb = new Set(b.toLowerCase().split(/\s+/).filter((w) => w.length > 2));
  if (ta.size === 0 || tb.size === 0) return 0;
  let inter = 0;
  for (const w of ta) if (tb.has(w)) inter++;
  return inter / Math.max(ta.size, tb.size);
}

function specificityScore(c: Claim): number {
  let s = 0;
  const txt = c.claim_text + " " + (c.target_entity || "");
  if (/\d+/.test(txt)) s += 2;
  if (/\b(pressare|costruire|rotazione|5-3-2|4-3-3|modulo)\b/i.test(txt)) s += 2;
  if (c.target_entity && c.target_entity.length > 1) s += 1;
  const qLen = c.evidence_quotes?.[0]?.quote_text?.length ?? 0;
  if (qLen > 30) s += 1;
  if (qLen > 60) s += 1;
  return s;
}

function quoteQuality(c: Claim): number {
  const q = c.evidence_quotes?.[0];
  if (!q) return 0;
  let s = q.confidence ?? 0.5;
  const len = q.quote_text?.length ?? 0;
  if (len > 20) s += 0.2;
  if (len > 50) s += 0.2;
  return s;
}

export interface AggregatorConfig {
  similarityThreshold?: number;
  maxClaims?: number;
}

export function aggregateVideoClaims(
  claims: Claim[],
  themes: Theme[],
  videoId: string,
  summaryShort: string,
  config: AggregatorConfig = {}
): VideoAnalysis {
  const threshold = config.similarityThreshold ?? 0.65;
  const maxClaims = config.maxClaims ?? 12;

  const kept: Claim[] = [];
  const used = new Set<number>();

  for (let i = 0; i < claims.length && kept.length < maxClaims; i++) {
    if (used.has(i)) continue;

    let bestIdx = i;
    for (let j = i + 1; j < claims.length; j++) {
      if (used.has(j)) continue;
      const sim = similarity(claims[i].claim_text, claims[j].claim_text);
      if (sim >= threshold) {
        const si = specificityScore(claims[i]) + quoteQuality(claims[i]);
        const sj = specificityScore(claims[j]) + quoteQuality(claims[j]);
        if (sj > si) bestIdx = j;
        used.add(j);
      }
    }
    if (!used.has(bestIdx)) {
      kept.push(claims[bestIdx]);
      used.add(bestIdx);
    }
  }

  // Sort by specificity + quote quality
  kept.sort((a, b) => {
    const sa = specificityScore(a) + quoteQuality(a);
    const sb = specificityScore(b) + quoteQuality(b);
    return sb - sa;
  });

  const finalClaims = kept.slice(0, maxClaims);

  // Normalize theme weights to 100
  const totalWeight = themes.reduce((s, t) => s + t.weight, 0) || 1;
  const normThemes: Theme[] = themes.map((t) => ({
    theme: t.theme,
    weight: Math.round((t.weight / totalWeight) * 100),
  }));

  return {
    video_id: videoId,
    themes: normThemes,
    claims: finalClaims,
    summary_short: summaryShort.slice(0, 600),
  };
}
