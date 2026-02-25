export interface Claim {
  topic: string;
  subject?: string;
  position: string;
  polarity?: "positive" | "negative" | "neutral";
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

export interface AnalysisResult {
  video_id: string;
  analyzed_at: string;
  metadata?: { title?: string; author_name?: string; published_at?: string };
  summary: string;
  topics: { name: string; relevance: "high" | "medium" | "low" }[];
  claims?: Claim[];
  evaluation?: VideoEvaluation;
}
