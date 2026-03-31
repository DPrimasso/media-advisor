/**
 * Step 2C — Merge claims at video level.
 * Semantic dedup, rank, max 12 claims, themes aggregated.
 */

import type { Claim, Theme, VideoAnalysis } from "../schema/claims.js";

/** Normalize theme name: strip English synonyms, Italian plural → singular, lowercase.
 *  Also sanitizes non-Italian non-ASCII chars (Romanian ț/ș, French œ, etc.) → Italian equivalent. */
function normalizeThemeName(raw: string): string {
  const sanitized = raw
    .replace(/[țţ]/gi, "t")  // Romanian t-cedilla → t
    .replace(/[șş]/gi, "s")  // Romanian s-cedilla → s
    .replace(/[ăâ]/gi, "a")  // Romanian a-variants → a
    .replace(/[îÎ]/g, "i")   // Romanian i-circumflex → i
    .replace(/ő/gi, "o")     // Hungarian o-double-acute → o
    .replace(/ű/gi, "u");    // Hungarian u-double-acute → u
  const t = sanitized.toLowerCase().trim();
  const synonyms: Record<string, string> = {
    injuries: "infortunio",
    injury: "infortunio",
    infortuni: "infortunio",
    performance: "prestazione",
    tactics: "tattica",
    leadership: "leadership",
    market: "mercato",
    motivation: "motivazione",
    finance: "finanza",
    rivalry: "rivalità",
    standings: "classifica",
    refereeing: "arbitraggio",
    nazionalita: "nazionalità",
    nationality: "nazionalità",
    nazionalità: "nazionalità",
    comunicazione: "comunicazione",
    communication: "comunicazione",
    lealta: "lealtà",
    lealtà: "lealtà",
    loyalty: "lealtà",
    dirigenza: "dirigenza",
    management: "dirigenza",
  };
  return synonyms[t] ?? t;
}

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
  const threshold = config.similarityThreshold ?? 0.40;
  const maxClaims = config.maxClaims ?? 12;

  // Drop trivial claims (intensity 0 = too vague or marginal to be useful)
  const substantive = claims.filter((c) => c.intensity > 0);

  const kept: Claim[] = [];
  const used = new Set<number>();

  for (let i = 0; i < substantive.length && kept.length < maxClaims; i++) {
    if (used.has(i)) continue;

    let bestIdx = i;
    for (let j = i + 1; j < substantive.length; j++) {
      if (used.has(j)) continue;
      const sim = similarity(substantive[i].claim_text, substantive[j].claim_text);
      if (sim >= threshold) {
        const si = specificityScore(substantive[i]) + quoteQuality(substantive[i]);
        const sj = specificityScore(substantive[j]) + quoteQuality(substantive[j]);
        if (sj > si) bestIdx = j;
        used.add(j);
      }
    }
    if (!used.has(bestIdx)) {
      kept.push(substantive[bestIdx]);
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

  // Deduplicate themes: normalize names (synonyms + Italian plural → singular) then merge
  const themeMap = new Map<string, number>();
  for (const t of themes) {
    const key = normalizeThemeName(t.theme);
    themeMap.set(key, (themeMap.get(key) ?? 0) + t.weight);
  }
  const dedupedThemes: Theme[] = Array.from(themeMap.entries()).map(([theme, weight]) => ({
    theme,
    weight,
  }));

  // Drop topics that are too generic to be useful
  const GENERIC_TOPICS = new Set([
    "calciatore", "giocatore", "squadra", "club", "legame", "calcio",
    "sport", "discussione", "analisi", "video", "tema", "argomento",
  ]);
  const meaningful = dedupedThemes.filter((t) => !GENERIC_TOPICS.has(t.theme));

  // Sort by weight descending, keep top 10
  meaningful.sort((a, b) => b.weight - a.weight);
  const topThemes = meaningful.slice(0, 10);

  // Normalize weights to 100
  const totalWeight = topThemes.reduce((s, t) => s + t.weight, 0) || 1;
  const normThemes: Theme[] = topThemes.map((t) => ({
    theme: t.theme,
    weight: Math.round((t.weight / totalWeight) * 100),
  }));

  return {
    video_id: videoId,
    themes: normThemes,
    claims: finalClaims,
    summary_short: summaryShort.slice(0, 1200),
  };
}
