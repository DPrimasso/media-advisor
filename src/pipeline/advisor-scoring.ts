import type { AnalysisResult, ClaimValidationStats } from "../analyzer/types.js";
import {
  CLAIM_TYPE_VALUES,
  DIMENSION_VALUES,
  ENTITY_TYPE_VALUES,
  MODALITY_VALUES,
  STANCE_VALUES,
  type Claim,
  type EvidenceQuote,
} from "../schema/claims.js";
import { detectInconsistencies } from "./inconsistency-detector.js";

const ABSOLUTE_PATTERNS =
  /\b(sempre|mai|tutti|nessuno|assolutamente|certamente|definitivamente)\b/i;
const VAGUE_WORDS =
  /\b(importante|merita|meritano|crescita|buon|bene|male|bella|bello|interessante|interessanti|particolare|particolari)\b/i;
const ACTION_VERBS =
  /\b(pressare|pressing|costruire|rotazione|modulo|formazione|5-3-2|4-3-3|scavare|gestione|allenare)\b/i;

type AnyClaim = NonNullable<AnalysisResult["claims"]>[number] & Record<string, unknown>;

export interface ChannelAdvisorScores {
  advisor_score: number;
  evidence_coverage: number;
  evidence_fidelity: number;
  specificity_score: number;
  coherence_score: number;
  prediction_accountability: number;
  bias_concentration: number;
  absolutism_rate: number;
  topic_diversity: number;
}

export interface ChannelAdvisorBreakdown {
  inconsistencies: {
    total: number;
    hard: number;
    soft: number;
    drift: number;
    not: number;
  };
  predictions: {
    total: number;
    open: number;
    resolved: number;
    hit: number;
    miss: number;
    unresolved: number;
    items: Array<{
      claim_id: string;
      video_id: string;
      published_at?: string;
      entity: string;
      topic: string;
      stance: "POS" | "NEG" | "NEU" | "MIXED";
      text: string;
      status: "open" | "hit" | "miss";
      confidence: number;
      resolved_by_video_id?: string;
      resolved_at?: string;
    }>;
  };
  top_entities: Array<{
    entity: string;
    total: number;
    positive: number;
    negative: number;
    neutral: number;
  }>;
  top_topics: Array<{ topic: string; total: number }>;
  validation: ClaimValidationStats;
}

export interface ChannelAdvisorReport {
  schema_version: string;
  channel_id: string;
  generated_at: string;
  videos_analyzed: number;
  claims_analyzed: number;
  scores: ChannelAdvisorScores;
  breakdown: ChannelAdvisorBreakdown;
}

function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

function toPct(num: number, den: number): number {
  if (den <= 0) return 0;
  return Math.round((num / den) * 100);
}

function str(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function num(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asEvidenceQuotes(value: unknown): EvidenceQuote[] {
  if (!Array.isArray(value)) return [];
  const quotes: EvidenceQuote[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") continue;
    const q = item as Record<string, unknown>;
    const quoteText = str(q.quote_text);
    const startSec = num(q.start_sec, NaN);
    const endSec = num(q.end_sec, NaN);
    if (!quoteText) continue;
    quotes.push({
      quote_text: quoteText,
      start_sec: Number.isFinite(startSec) ? startSec : 0,
      end_sec: Number.isFinite(endSec) ? endSec : Number.isFinite(startSec) ? startSec : 0,
      confidence: clamp(num(q.confidence, 0.5), 0, 1),
    });
  }
  return quotes;
}

function hasEvidence(claim: AnyClaim): boolean {
  const q = asEvidenceQuotes(claim.evidence_quotes)[0];
  return !!q?.quote_text && Number.isFinite(q.start_sec);
}

function polarityOf(claim: AnyClaim): "positive" | "negative" | "neutral" {
  const pol = str(claim.polarity).toLowerCase();
  if (pol === "positive") return "positive";
  if (pol === "negative") return "negative";
  const stance = str(claim.stance).toUpperCase();
  if (stance === "POS") return "positive";
  if (stance === "NEG") return "negative";
  return "neutral";
}

function topicOf(claim: AnyClaim): string {
  return str(claim.topic) || str(claim.dimension) || "generale";
}

function entityOf(claim: AnyClaim): string {
  return str(claim.subject) || str(claim.target_entity) || "generale";
}

function claimTextOf(claim: AnyClaim): string {
  return str(claim.claim_text) || str(claim.position);
}

function specificityRaw(claim: AnyClaim): number {
  const text = claimTextOf(claim);
  const entity = entityOf(claim);
  let s = 0;
  if (/\d+/.test(text)) s += 2;
  if (ACTION_VERBS.test(text)) s += 2;
  if (entity.length > 2) s += 1;
  if (VAGUE_WORDS.test(text) && !ACTION_VERBS.test(text) && !/\d+/.test(text)) s -= 2;
  const words = text.split(/\s+/).filter(Boolean).length;
  if (words >= 8 && words <= 25) s += 1;
  if (words < 5) s -= 1;
  return s;
}

function normalizeSpecificity(avgRaw: number): number {
  return clamp(Math.round(((avgRaw + 2) / 8) * 100), 0, 100);
}

function normalizedEntropy(values: number[]): number {
  const total = values.reduce((acc, n) => acc + n, 0);
  if (total <= 0) return 0;
  const nonZero = values.filter((n) => n > 0);
  if (nonZero.length <= 1) return 0;
  const entropy = -nonZero.reduce((acc, n) => {
    const p = n / total;
    return acc + p * Math.log(p);
  }, 0);
  return clamp(Math.round((entropy / Math.log(nonZero.length)) * 100), 0, 100);
}

function normalizeFromSet<T extends string>(value: string, allowed: readonly T[], fallback: T): T {
  return (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
}

function dateMs(iso?: string): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? ms : null;
}

function directionalStanceWeight(stance: Claim["stance"]): { pos: number; neg: number } {
  if (stance === "POS") return { pos: 1, neg: 0 };
  if (stance === "NEG") return { pos: 0, neg: 1 };
  if (stance === "MIXED") return { pos: 0.5, neg: 0.5 };
  return { pos: 0, neg: 0 };
}

function toStructuredClaim(claim: AnyClaim, videoId: string, idx: number): Claim {
  const entityType = normalizeFromSet(
    str(claim.entity_type),
    ENTITY_TYPE_VALUES,
    "other"
  );
  const dimension = normalizeFromSet(
    str(claim.dimension) || str(claim.topic),
    DIMENSION_VALUES,
    "media"
  );
  const claimType = normalizeFromSet(
    str(claim.claim_type),
    CLAIM_TYPE_VALUES,
    "INTERPRETATION"
  );
  const stance = normalizeFromSet(
    str(claim.stance),
    STANCE_VALUES,
    polarityOf(claim) === "positive"
      ? "POS"
      : polarityOf(claim) === "negative"
        ? "NEG"
        : "NEU"
  );
  const modality = normalizeFromSet(
    str(claim.modality),
    MODALITY_VALUES,
    "PROBABLE"
  );
  const rawIntensity = Math.round(num(claim.intensity, 1));
  const intensity = clamp(rawIntensity, 0, 3) as 0 | 1 | 2 | 3;
  const text = claimTextOf(claim) || "Claim non disponibile";
  const quotes = asEvidenceQuotes(claim.evidence_quotes);

  return {
    claim_id: str(claim.claim_id, `${videoId}-c${idx}`),
    video_id: videoId,
    segment_id: str(claim.segment_id, `s${idx}`),
    target_entity: entityOf(claim),
    entity_type: entityType,
    dimension,
    claim_type: claimType,
    stance,
    intensity,
    modality,
    claim_text: text,
    evidence_quotes: quotes.length
      ? quotes.slice(0, 2)
      : [
          {
            quote_text: text,
            start_sec: 0,
            end_sec: 0,
            confidence: 0.1,
          },
        ],
    tags: Array.isArray(claim.tags)
      ? claim.tags
          .filter((t): t is string => typeof t === "string")
          .slice(0, 6)
      : [],
  };
}

export function buildChannelAdvisorReport(
  channelId: string,
  analyses: AnalysisResult[]
): ChannelAdvisorReport {
  const claimsWithMeta: Array<{ claim: AnyClaim; video_id: string; published_at?: string }> = [];
  const validationAgg: ClaimValidationStats = {
    total: 0,
    supported: 0,
    repaired: 0,
    dropped: 0,
  };

  for (const analysis of analyses) {
    const claims = (analysis.claims ?? []) as AnyClaim[];
    for (const c of claims) {
      claimsWithMeta.push({
        claim: c,
        video_id: analysis.video_id,
        published_at: analysis.metadata?.published_at,
      });
    }
    if (analysis.quality?.validation) {
      validationAgg.total += analysis.quality.validation.total;
      validationAgg.supported += analysis.quality.validation.supported;
      validationAgg.repaired += analysis.quality.validation.repaired;
      validationAgg.dropped += analysis.quality.validation.dropped;
    }
  }

  const totalClaims = claimsWithMeta.length;
  const evidenceClaims = claimsWithMeta.filter(({ claim }) => hasEvidence(claim)).length;
  const evidenceCoverage = toPct(evidenceClaims, totalClaims);
  const evidenceFidelity =
    validationAgg.total > 0
      ? toPct(validationAgg.supported + validationAgg.repaired, validationAgg.total)
      : evidenceCoverage;

  const specificityAvg =
    totalClaims > 0
      ? claimsWithMeta.reduce((acc, { claim }) => acc + specificityRaw(claim), 0) / totalClaims
      : 0;
  const specificityScore = normalizeSpecificity(specificityAvg);

  const claimsMap = new Map<string, Array<Claim & { published_at?: string }>>();
  const videoDates = new Map<string, string>();
  const structuredClaims: Array<Claim & { published_at?: string }> = claimsWithMeta.map(
    ({ claim, video_id, published_at }, idx) => {
      if (published_at) videoDates.set(video_id, published_at);
      return {
        ...toStructuredClaim(claim, video_id, idx),
        published_at,
      };
    }
  );
  claimsMap.set(channelId, structuredClaims);
  const inconsistencies = detectInconsistencies(claimsMap, videoDates);
  let hard = 0;
  let soft = 0;
  let drift = 0;
  let not = 0;
  for (const ev of inconsistencies) {
    if (ev.type === "HARD") hard++;
    else if (ev.type === "SOFT") soft++;
    else if (ev.type === "DRIFT") drift++;
    else not++;
  }
  const weightedInconsistencies = hard + soft * 0.6 + drift * 0.3;
  const coherencePenalty =
    totalClaims > 0 ? clamp((weightedInconsistencies / totalClaims) * 220, 0, 100) : 0;
  const coherenceScore = clamp(Math.round(100 - coherencePenalty), 0, 100);

  const predictionClaims = structuredClaims
    .filter((c) => c.claim_type === "PREDICTION")
    .sort((a, b) => {
      const da = dateMs(a.published_at);
      const db = dateMs(b.published_at);
      if (da == null && db == null) return a.video_id.localeCompare(b.video_id);
      if (da == null) return 1;
      if (db == null) return -1;
      return da - db;
    });

  const predictionItems: ChannelAdvisorBreakdown["predictions"]["items"] = [];
  let predictionHit = 0;
  let predictionMiss = 0;

  for (const pred of predictionClaims) {
    const predDate = dateMs(pred.published_at);
    const futureClaims = structuredClaims.filter((c) => {
      if (c.video_id === pred.video_id) return false;
      if (c.target_entity.toLowerCase() !== pred.target_entity.toLowerCase()) return false;
      if (c.dimension !== pred.dimension) return false;
      if (c.claim_type === "PREDICTION") return false;
      if (predDate == null) return false;
      const cDate = dateMs(c.published_at);
      return cDate != null && cDate > predDate;
    });

    let status: "open" | "hit" | "miss" = "open";
    let confidence = 0;
    let resolvedByVideoId: string | undefined;
    let resolvedAt: string | undefined;

    if (futureClaims.length > 0 && (pred.stance === "POS" || pred.stance === "NEG")) {
      let pos = 0;
      let neg = 0;
      for (const c of futureClaims) {
        const w = directionalStanceWeight(c.stance);
        pos += w.pos;
        neg += w.neg;
      }
      const directionalTotal = pos + neg;
      if (directionalTotal > 0 && pos !== neg) {
        const majority: "POS" | "NEG" = pos > neg ? "POS" : "NEG";
        status = majority === pred.stance ? "hit" : "miss";
        confidence = clamp(Math.round((Math.abs(pos - neg) / directionalTotal) * 100), 0, 100);
        if (status === "hit") predictionHit++;
        else predictionMiss++;
        const resolutionClaim = futureClaims.find(
          (c) => (majority === "POS" && c.stance === "POS") || (majority === "NEG" && c.stance === "NEG")
        );
        resolvedByVideoId = resolutionClaim?.video_id;
        resolvedAt = resolutionClaim?.published_at;
      }
    }

    predictionItems.push({
      claim_id: pred.claim_id,
      video_id: pred.video_id,
      published_at: pred.published_at,
      entity: pred.target_entity,
      topic: pred.dimension,
      stance: pred.stance,
      text: pred.claim_text,
      status,
      confidence,
      resolved_by_video_id: resolvedByVideoId,
      resolved_at: resolvedAt,
    });
  }

  const predictionBreakdown = {
    total: predictionClaims.length,
    open: predictionItems.filter((p) => p.status === "open").length,
    resolved: predictionHit + predictionMiss,
    hit: predictionHit,
    miss: predictionMiss,
    unresolved: predictionItems.filter((p) => p.status === "open").length,
    items: predictionItems.slice(0, 30),
  };
  const predictionAccountability =
    predictionBreakdown.total === 0
      ? 50
      : predictionBreakdown.resolved === 0
        ? 0
        : clamp(Math.round((predictionBreakdown.hit / predictionBreakdown.resolved) * 100), 0, 100);

  let absolutismCount = 0;
  for (const { claim } of claimsWithMeta) {
    if (ABSOLUTE_PATTERNS.test(claimTextOf(claim))) absolutismCount++;
  }
  const absolutismRate = toPct(absolutismCount, totalClaims);

  const byEntity = new Map<string, { total: number; positive: number; negative: number; neutral: number }>();
  for (const { claim } of claimsWithMeta) {
    const entity = entityOf(claim);
    if (!byEntity.has(entity)) byEntity.set(entity, { total: 0, positive: 0, negative: 0, neutral: 0 });
    const row = byEntity.get(entity)!;
    row.total++;
    const pol = polarityOf(claim);
    if (pol === "positive") row.positive++;
    else if (pol === "negative") row.negative++;
    else row.neutral++;
  }

  let concentrationWeighted = 0;
  let concentrationWeight = 0;
  for (const stats of byEntity.values()) {
    const directional = stats.positive + stats.negative;
    if (directional <= 0) continue;
    const imbalance = Math.abs(stats.positive - stats.negative) / directional;
    concentrationWeighted += imbalance * directional;
    concentrationWeight += directional;
  }
  const biasConcentration =
    concentrationWeight > 0
      ? clamp(Math.round((concentrationWeighted / concentrationWeight) * 100), 0, 100)
      : 0;

  const byTopic = new Map<string, number>();
  for (const { claim } of claimsWithMeta) {
    const topic = topicOf(claim);
    byTopic.set(topic, (byTopic.get(topic) ?? 0) + 1);
  }
  const topicDiversity = normalizedEntropy([...byTopic.values()]);

  const advisorScore = clamp(
    Math.round(
      0.2 * evidenceCoverage +
        0.2 * evidenceFidelity +
        0.2 * coherenceScore +
        0.15 * specificityScore +
        0.1 * predictionAccountability +
        0.1 * (100 - biasConcentration) +
        0.05 * (100 - absolutismRate)
    ),
    0,
    100
  );

  const topEntities = [...byEntity.entries()]
    .map(([entity, s]) => ({ entity, ...s }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 20);
  const topTopics = [...byTopic.entries()]
    .map(([topic, total]) => ({ topic, total }))
    .sort((a, b) => b.total - a.total)
    .slice(0, 20);

  return {
    schema_version: "1.0.0",
    channel_id: channelId,
    generated_at: new Date().toISOString(),
    videos_analyzed: analyses.length,
    claims_analyzed: totalClaims,
    scores: {
      advisor_score: advisorScore,
      evidence_coverage: evidenceCoverage,
      evidence_fidelity: evidenceFidelity,
      specificity_score: specificityScore,
      coherence_score: coherenceScore,
      prediction_accountability: predictionAccountability,
      bias_concentration: biasConcentration,
      absolutism_rate: absolutismRate,
      topic_diversity: topicDiversity,
    },
    breakdown: {
      inconsistencies: {
        total: inconsistencies.length,
        hard,
        soft,
        drift,
        not,
      },
      predictions: predictionBreakdown,
      top_entities: topEntities,
      top_topics: topTopics,
      validation: validationAgg,
    },
  };
}
