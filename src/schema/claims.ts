/**
 * Step 2A — Schema dati per claims strutturati.
 */

export const DIMENSION_VALUES = [
  "performance",
  "tactics",
  "market",
  "finance",
  "leadership",
  "injury",
  "lineup_prediction",
  "refereeing",
  "fan_behavior",
  "standings",
  "europe",
  "rivalry",
  "media",
] as const;

export const CLAIM_TYPE_VALUES = [
  "FACT",
  "OBSERVATION",
  "INTERPRETATION",
  "JUDGEMENT",
  "PRESCRIPTION",
  "PREDICTION",
  "META_INFO_QUALITY",
] as const;

export const STANCE_VALUES = ["POS", "NEG", "NEU", "MIXED"] as const;

export const MODALITY_VALUES = [
  "CERTAIN",
  "PROBABLE",
  "POSSIBLE",
  "HYPOTHESIS",
  "PRESCRIPTIVE",
] as const;

export const ENTITY_TYPE_VALUES = ["team", "player", "coach", "ref", "club", "other"] as const;

export interface EvidenceQuote {
  quote_text: string;
  start_sec: number;
  end_sec: number;
  confidence: number;
}

export interface Claim {
  claim_id: string;
  video_id: string;
  segment_id: string;
  target_entity: string;
  entity_type: (typeof ENTITY_TYPE_VALUES)[number];
  dimension: (typeof DIMENSION_VALUES)[number];
  claim_type: (typeof CLAIM_TYPE_VALUES)[number];
  stance: (typeof STANCE_VALUES)[number];
  intensity: 0 | 1 | 2 | 3;
  modality: (typeof MODALITY_VALUES)[number];
  claim_text: string;
  evidence_quotes: EvidenceQuote[];
  tags: string[];
}

export interface Theme {
  theme: string;
  weight: number;
}

export interface RhetoricalTechnique {
  technique: string;
  example: string;
  frequency: "low" | "medium" | "high";
}

export interface VideoEvaluation {
  factuality_index: number;
  objectivity_index: number;
  argumentation_quality: number;
  information_density: number;
  sensationalism_index: number;
  source_reliability: number;
  overall_credibility: number;
  emotional_tone: string[];
  rhetorical_techniques: RhetoricalTechnique[];
  content_type_breakdown: {
    facts_pct: number;
    opinions_pct: number;
    predictions_pct: number;
    prescriptions_pct: number;
  };
  key_strengths: string[];
  key_weaknesses: string[];
}

export interface VideoAnalysis {
  video_id: string;
  themes: Theme[];
  claims: Claim[];
  summary_short: string;
  summary_long?: string;
  evaluation?: VideoEvaluation;
}

export function validateClaim(c: Partial<Claim>): { ok: boolean; error?: string } {
  if (!c.claim_id || !c.video_id || !c.segment_id) return { ok: false, error: "Missing ids" };
  if (!c.evidence_quotes?.length) return { ok: false, error: "Claim must have at least one evidence_quote" };
  if (!c.claim_text || c.claim_text.length < 15) return { ok: false, error: "claim_text too short/generic" };
  if ((c.tags?.length ?? 0) > 6) return { ok: false, error: "Max 6 tags" };
  if ((c.evidence_quotes?.length ?? 0) > 2) return { ok: false, error: "Max 2 evidence_quotes" };
  return { ok: true };
}
