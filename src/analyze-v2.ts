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
import { generateSummary } from "./pipeline/summarizer.js";
import type { TranscriptResponse } from "./transcript-client.js";
import type { Claim } from "./schema/claims.js";
import type { AnalysisResult } from "./analyzer/types.js";

function stanceToPolarity(s: string): "positive" | "negative" | "neutral" {
  if (s === "POS") return "positive";
  if (s === "NEG") return "negative";
  return "neutral";
}

function weightToRelevance(w: number, rank: number): "high" | "medium" | "low" {
  if (rank === 0) return "high";
  if (rank <= 2) return "high";
  if (rank <= 5) return "medium";
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

  // Drop meta-claims about the journalist/host (self-introduction, format descriptions)
  const META_CLAIM = /\b(appassionato|l'opinionista|l'autore|si chiama|è un commentatore|parla di calcio|è il canale|è il creatore|vuole rispondere|risponde ai fan|risponde alle domande)\b/i;
  const META_ENTITY = /^(opinionista|autore|commentatore|valerio fluido|valerio|creator|host)$/i;

  // Drop misattributed claims: entities cited as comparison/precedent but labelled as "commented on"
  // e.g. De Bruyne appears as a rehab reference, not as a commentator on Lukaku
  const MISATTRIBUTED_ENTITY = /^(de bru[yi]n[e]?|debruyne?)$/i;
  const MISATTRIBUTED_VERB = /\b(ha commentato|commenta(ndo)?|ha dichiarato|ha detto|ha parlato di|ha espresso)\b/i;

  const filtered = filterBySpecificity(allClaims).filter(
    (c) =>
      !META_CLAIM.test(c.claim_text) &&
      !META_ENTITY.test(c.target_entity ?? "") &&
      !(MISATTRIBUTED_ENTITY.test(c.target_entity ?? "") && MISATTRIBUTED_VERB.test(c.claim_text))
  );

  const fullText = clean.map((s) => s.text).join(" ");
  const summaryShort = await generateSummary(openai, {
    title: metadata?.title ?? data.metadata?.title,
    author: data.metadata?.author_name ?? channelId,
    fullText,
    claims: filtered,
  });

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
    topics: (analysis.themes ?? []).map((t, i) => ({
      name: t.theme,
      relevance: weightToRelevance(t.weight, i),
    })),
    claims: compatClaims as import("./analyzer/types.js").AnalysisResult["claims"],
  };
}
