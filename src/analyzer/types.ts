export interface Claim {
  topic: string;
  subject?: string;
  position: string;
  polarity?: "positive" | "negative" | "neutral";
}

export interface AnalysisResult {
  video_id: string;
  analyzed_at: string;
  metadata?: { title?: string; author_name?: string; published_at?: string };
  summary: string;
  topics: { name: string; relevance: "high" | "medium" | "low" }[];
  claims?: Claim[];
}
