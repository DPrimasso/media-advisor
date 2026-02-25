export interface Claim {
  topic: string;
  subject?: string;
  position: string;
  polarity?: "positive" | "negative" | "neutral";
}

export interface ClaimValidationStats {
  total: number;
  supported: number;
  repaired: number;
  dropped: number;
}

export interface VideoQualityMetrics {
  evidence_coverage: number;
  evidence_fidelity: number;
  validation: ClaimValidationStats;
}

export interface AnalysisResult {
  video_id: string;
  analyzed_at: string;
  metadata?: { title?: string; author_name?: string; published_at?: string };
  summary: string;
  topics: { name: string; relevance: "high" | "medium" | "low" }[];
  claims?: Claim[];
  quality?: VideoQualityMetrics;
}
