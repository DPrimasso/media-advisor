/**
 * Step 5 — Channel profiler: stance by entity, top themes, language patterns.
 */

import type { Claim, VideoAnalysis } from "../schema/claims.js";

export interface EntityStance {
  entity: string;
  avg_stance: "POS" | "NEG" | "NEU" | "MIXED";
  intensity_avg: number;
  frequency: number;
  pos_count: number;
  neg_count: number;
  neu_count: number;
}

export interface ChannelProfile {
  channel_id: string;
  top_themes: Array<{ theme: string; pct: number }>;
  stance_by_entity: EntityStance[];
  language_patterns: {
    pct_absolutes: number;
    pct_prescriptions: number;
    pct_interpretations: number;
    pct_facts: number;
  };
  signature_claim_clusters: string[];
  total_claims: number;
}

const ABSOLUTE_PATTERNS = /\b(sempre|mai|tutti|nessuno|sempre|assolutamente|certamente|definitivamente)\b/i;

export function buildChannelProfile(
  channelId: string,
  analyses: VideoAnalysis[]
): ChannelProfile {
  const allClaims = analyses.flatMap((a) => a.claims ?? []);
  const allThemes = analyses.flatMap((a) => a.themes ?? []);

  const themeCounts = new Map<string, number>();
  for (const t of allThemes) {
    themeCounts.set(t.theme, (themeCounts.get(t.theme) ?? 0) + (t.weight ?? 1));
  }
  const themeTotal = [...themeCounts.values()].reduce((a, b) => a + b, 0) || 1;
  const topThemes = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 15)
    .map(([theme, cnt]) => ({ theme, pct: Math.round((cnt / themeTotal) * 100) }));

  const byEntity = new Map<string, Claim[]>();
  for (const c of allClaims) {
    const e = c.target_entity || "generale";
    if (!byEntity.has(e)) byEntity.set(e, []);
    byEntity.get(e)!.push(c);
  }

  const stanceByEntity: EntityStance[] = [];
  for (const [entity, claims] of byEntity) {
    let pos = 0,
      neg = 0,
      neu = 0,
      mix = 0;
    let intensitySum = 0;
    for (const c of claims) {
      if (c.stance === "POS") pos++;
      else if (c.stance === "NEG") neg++;
      else if (c.stance === "NEU") neu++;
      else mix++;
      intensitySum += c.intensity ?? 1;
    }
    const total = claims.length;
    let avgStance: EntityStance["avg_stance"] = "NEU";
    if (pos > neg && pos > neu) avgStance = "POS";
    else if (neg > pos && neg > neu) avgStance = "NEG";
    else if (mix > total / 2) avgStance = "MIXED";

    stanceByEntity.push({
      entity,
      avg_stance: avgStance,
      intensity_avg: total ? Math.round((intensitySum / total) * 10) / 10 : 0,
      frequency: total,
      pos_count: pos,
      neg_count: neg,
      neu_count: neu,
    });
  }
  stanceByEntity.sort((a, b) => b.frequency - a.frequency);

  let absolutes = 0,
    prescriptions = 0,
    interpretations = 0,
    facts = 0;
  for (const c of allClaims) {
    if (ABSOLUTE_PATTERNS.test(c.claim_text)) absolutes++;
    if (c.claim_type === "PRESCRIPTION") prescriptions++;
    else if (c.claim_type === "INTERPRETATION") interpretations++;
    else if (c.claim_type === "FACT") facts++;
  }
  const n = allClaims.length || 1;

  const signatureClusters = [...themeCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([t]) => t);

  return {
    channel_id: channelId,
    top_themes: topThemes,
    stance_by_entity: stanceByEntity,
    language_patterns: {
      pct_absolutes: Math.round((absolutes / n) * 100),
      pct_prescriptions: Math.round((prescriptions / n) * 100),
      pct_interpretations: Math.round((interpretations / n) * 100),
      pct_facts: Math.round((facts / n) * 100),
    },
    signature_claim_clusters: signatureClusters,
    total_claims: allClaims.length,
  };
}
