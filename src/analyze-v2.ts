/**
 * V2 single-video analyzer: transcript → clean → segment → extract → aggregate → filter.
 * Outputs format compatible with channel-analyze + UI (claims with evidence_quotes, timestamp).
 */

import OpenAI from "openai";
import { cleanTranscript } from "./pipeline/transcript-cleaner.js";
import { segment } from "./pipeline/segmenter.js";
import { extractClaimsFromSegment } from "./pipeline/extractor.js";
import { aggregateVideoClaims } from "./pipeline/video-aggregator.js";
import { filterBySpecificity } from "./pipeline/specificity-filter.js";
import { normalizeClaimEntities } from "./pipeline/entity-normalizer.js";
import type { TranscriptResponse } from "./transcript-client.js";
import type { Claim } from "./schema/claims.js";
import type { AnalysisResult } from "./analyzer/types.js";

function stanceToPolarity(s: string): "positive" | "negative" | "neutral" {
  if (s === "POS") return "positive";
  if (s === "NEG") return "negative";
  return "neutral";
}

function weightToRelevance(w: number): "high" | "medium" | "low" {
  if (w >= 20) return "high";
  if (w >= 10) return "medium";
  return "low";
}

/** Merge v2 claim with channel-analyze fields (topic, subject, position, polarity) */
function toCompatClaim(c: Claim): import("./analyzer/types.js").Claim & Record<string, unknown> {
  return {
    ...c,
    topic: c.dimension,
    subject: c.target_entity || undefined,
    position: c.claim_text,
    polarity: stanceToPolarity(c.stance),
  };
}

export interface AnalyzeV2Options {
  openai: OpenAI;
  data: TranscriptResponse;
  videoId: string;
  channelId: string;
  metadata?: { title?: string; published_at?: string };
}

export async function analyzeVideoV2(opts: AnalyzeV2Options): Promise<AnalysisResult> {
  const { openai, data, videoId, channelId, metadata } = opts;

  if (!data.transcript || (Array.isArray(data.transcript) && data.transcript.length === 0)) {
    throw new Error("Empty transcript");
  }

  const clean = cleanTranscript(data);
  const segments = segment(clean, { mode: "topic_shift", max_segments: 12 });

  const allClaims: Claim[] = [];
  const allThemes: { theme: string; weight: number }[] = [];

  for (const seg of segments) {
    const { claims, themes } = await extractClaimsFromSegment(openai, {
      segment: seg,
      video_id: videoId,
      context: {
        title: metadata?.title,
        published_at: metadata?.published_at,
        opinionist: channelId,
      },
    });
    for (const c of claims) {
      allClaims.push(normalizeClaimEntities(c));
    }
    allThemes.push(...themes);
  }

  const filtered = filterBySpecificity(allClaims);
  const summaryShort =
    (metadata?.title ?? data.metadata?.title ?? "Video") +
    " — " +
    (metadata?.published_at ?? data.metadata?.published_at ?? "").slice(0, 10);

  const analysis = aggregateVideoClaims(
    filtered,
    allThemes,
    videoId,
    summaryShort,
    { maxClaims: 12 }
  );

  const compatClaims = (analysis.claims ?? []).map(toCompatClaim);

  return {
    video_id: videoId,
    analyzed_at: new Date().toISOString(),
    metadata: data.metadata
      ? {
          title: data.metadata.title,
          author_name: data.metadata.author_name,
          published_at: data.metadata.published_at,
        }
      : undefined,
    summary: analysis.summary_short,
    topics: (analysis.themes ?? []).map((t) => ({
      name: t.theme,
      relevance: weightToRelevance(t.weight),
    })),
    claims: compatClaims as import("./analyzer/types.js").AnalysisResult["claims"],
  };
}
