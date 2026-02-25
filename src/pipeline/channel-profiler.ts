/**
 * Step 5 — Channel profiler: stance by entity, top themes, language patterns, evaluation aggregates.
 */

import type { Claim, VideoAnalysis, VideoEvaluation } from "../schema/claims.js";

export interface EntityStance {
  entity: string;
  avg_stance: "POS" | "NEG" | "NEU" | "MIXED";
  intensity_avg: number;
  frequency: number;
  pos_count: number;
  neg_count: number;
  neu_count: number;
}

export interface AggregateEvaluation {
  factuality_index: number;
  objectivity_index: number;
  argumentation_quality: number;
  information_density: number;
  sensationalism_index: number;
  source_reliability: number;
  overall_credibility: number;
  common_emotional_tones: string[];
  common_rhetorical_techniques: { technique: string; occurrences: number }[];
  avg_content_breakdown: {
    facts_pct: number;
    opinions_pct: number;
    predictions_pct: number;
    prescriptions_pct: number;
  };
  common_strengths: string[];
  common_weaknesses: string[];
  videos_evaluated: number;
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
  aggregate_evaluation?: AggregateEvaluation;
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

  const aggregateEval = buildAggregateEvaluation(analyses);

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
    aggregate_evaluation: aggregateEval,
  };
}

function buildAggregateEvaluation(analyses: VideoAnalysis[]): AggregateEvaluation | undefined {
  const evals = analyses
    .map((a) => a.evaluation)
    .filter((e): e is VideoEvaluation => !!e);

  if (evals.length === 0) return undefined;

  const avg = (getter: (e: VideoEvaluation) => number) =>
    Math.round(evals.reduce((s, e) => s + getter(e), 0) / evals.length);

  const toneCounts = new Map<string, number>();
  for (const e of evals) {
    for (const t of e.emotional_tone ?? []) {
      toneCounts.set(t, (toneCounts.get(t) ?? 0) + 1);
    }
  }
  const commonTones = [...toneCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([t]) => t);

  const techCounts = new Map<string, number>();
  for (const e of evals) {
    for (const t of e.rhetorical_techniques ?? []) {
      techCounts.set(t.technique, (techCounts.get(t.technique) ?? 0) + 1);
    }
  }
  const commonTechs = [...techCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([technique, occurrences]) => ({ technique, occurrences }));

  const strengthCounts = new Map<string, number>();
  const weaknessCounts = new Map<string, number>();
  for (const e of evals) {
    for (const s of e.key_strengths ?? []) strengthCounts.set(s, (strengthCounts.get(s) ?? 0) + 1);
    for (const w of e.key_weaknesses ?? []) weaknessCounts.set(w, (weaknessCounts.get(w) ?? 0) + 1);
  }

  return {
    factuality_index: avg((e) => e.factuality_index),
    objectivity_index: avg((e) => e.objectivity_index),
    argumentation_quality: avg((e) => e.argumentation_quality),
    information_density: avg((e) => e.information_density),
    sensationalism_index: avg((e) => e.sensationalism_index),
    source_reliability: avg((e) => e.source_reliability),
    overall_credibility: avg((e) => e.overall_credibility),
    common_emotional_tones: commonTones,
    common_rhetorical_techniques: commonTechs,
    avg_content_breakdown: {
      facts_pct: avg((e) => e.content_type_breakdown?.facts_pct ?? 0),
      opinions_pct: avg((e) => e.content_type_breakdown?.opinions_pct ?? 0),
      predictions_pct: avg((e) => e.content_type_breakdown?.predictions_pct ?? 0),
      prescriptions_pct: avg((e) => e.content_type_breakdown?.prescriptions_pct ?? 0),
    },
    common_strengths: [...strengthCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([s]) => s),
    common_weaknesses: [...weaknessCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5).map(([s]) => s),
    videos_evaluated: evals.length,
  };
}
