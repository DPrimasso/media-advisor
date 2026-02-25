import { existsSync } from "node:fs";
import { readdir, readFile, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { AnalysisResult } from "./analyzer/types.js";
import {
  buildChannelAdvisorReport,
  type BuildChannelAdvisorOptions,
  type ChannelAdvisorReport,
} from "./pipeline/advisor-scoring.js";

const ADVISOR_FILE = "_advisor.json";

function finiteNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function normalizeAnalysis(
  raw: Record<string, unknown> & { video_id: string }
): AnalysisResult | null {
  if (!raw.video_id) return null;

  const summary =
    typeof raw.summary === "string"
      ? raw.summary
      : typeof raw.summary_short === "string"
        ? raw.summary_short
        : "";
  const topicsRaw = Array.isArray(raw.topics) ? raw.topics : Array.isArray(raw.themes) ? raw.themes : [];
  const topics = topicsRaw
    .map((t) => {
      if (!t || typeof t !== "object") return null;
      const obj = t as Record<string, unknown>;
      const name =
        typeof obj.name === "string"
          ? obj.name
          : typeof obj.theme === "string"
            ? obj.theme
            : "";
      if (!name) return null;
      let relevance: "high" | "medium" | "low" = "low";
      if (obj.relevance === "high" || obj.relevance === "medium" || obj.relevance === "low") {
        relevance = obj.relevance;
      } else {
        const weight = finiteNumber(obj.weight, 0);
        relevance = weight >= 20 ? "high" : weight >= 10 ? "medium" : "low";
      }
      return { name, relevance };
    })
    .filter((t): t is { name: string; relevance: "high" | "medium" | "low" } => !!t);

  const claimsRaw = Array.isArray(raw.claims) ? raw.claims : [];
  const claims: NonNullable<AnalysisResult["claims"]> = [];
  for (const c of claimsRaw) {
    if (!c || typeof c !== "object") continue;
    const obj = c as Record<string, unknown>;
    const topic =
      typeof obj.topic === "string"
        ? obj.topic
        : typeof obj.dimension === "string"
          ? obj.dimension
          : "";
    const position =
      typeof obj.position === "string"
        ? obj.position
        : typeof obj.claim_text === "string"
          ? obj.claim_text
          : "";
    if (!topic || !position) continue;
    const subject =
      typeof obj.subject === "string"
        ? obj.subject
        : typeof obj.target_entity === "string"
          ? obj.target_entity
          : undefined;
    const polarity =
      obj.polarity === "positive" || obj.polarity === "negative" || obj.polarity === "neutral"
        ? obj.polarity
        : obj.stance === "POS"
          ? "positive"
          : obj.stance === "NEG"
            ? "negative"
            : "neutral";
    claims.push({
      ...obj,
      topic,
      subject,
      position,
      polarity,
    });
  }

  const qualityRaw =
    raw.quality && typeof raw.quality === "object"
      ? (raw.quality as Record<string, unknown>)
      : null;
  const validationRaw =
    qualityRaw?.validation && typeof qualityRaw.validation === "object"
      ? (qualityRaw.validation as Record<string, unknown>)
      : null;
  const quality = qualityRaw && validationRaw
    ? {
        evidence_coverage: clampPct(finiteNumber(qualityRaw.evidence_coverage, 0)),
        evidence_fidelity: clampPct(finiteNumber(qualityRaw.evidence_fidelity, 0)),
        validation: {
          total: Math.max(0, Math.round(finiteNumber(validationRaw.total, 0))),
          supported: Math.max(0, Math.round(finiteNumber(validationRaw.supported, 0))),
          repaired: Math.max(0, Math.round(finiteNumber(validationRaw.repaired, 0))),
          dropped: Math.max(0, Math.round(finiteNumber(validationRaw.dropped, 0))),
        },
      }
    : undefined;

  return {
    video_id: raw.video_id,
    analyzed_at: typeof raw.analyzed_at === "string" ? raw.analyzed_at : new Date().toISOString(),
    metadata:
      raw.metadata && typeof raw.metadata === "object"
        ? (raw.metadata as AnalysisResult["metadata"])
        : undefined,
    summary,
    topics,
    claims,
    quality,
  };
}

function clampPct(value: number): number {
  return Math.min(100, Math.max(0, Math.round(value)));
}

export async function generateChannelAdvisor(
  channelId: string,
  channelAnalysisDir: string,
  options?: BuildChannelAdvisorOptions & { minFidelity?: number }
): Promise<ChannelAdvisorReport | null> {
  if (!existsSync(channelAnalysisDir)) return null;
  const files = (await readdir(channelAnalysisDir)).filter(
    (f) => f.endsWith(".json") && !f.startsWith("_")
  );
  if (files.length === 0) return null;

  const analyses: AnalysisResult[] = [];
  for (const file of files) {
    try {
      const raw = JSON.parse(
        await readFile(join(channelAnalysisDir, file), "utf-8")
      ) as Record<string, unknown> & { video_id: string };
      const normalized = normalizeAnalysis(raw);
      if (normalized) analyses.push(normalized);
    } catch {
      // skip malformed analysis file
    }
  }
  if (analyses.length === 0) return null;

  const report = buildChannelAdvisorReport(channelId, analyses, options);
  const minFidelity = Math.max(0, Math.min(100, Math.round(options?.minFidelity ?? 0)));
  if (minFidelity > 0 && report.scores.evidence_fidelity < minFidelity) {
    const advisorPath = join(channelAnalysisDir, ADVISOR_FILE);
    if (existsSync(advisorPath)) {
      try {
        await unlink(advisorPath);
      } catch {
        // ignore unlink issues; skip generation anyway
      }
    }
    return null;
  }
  await writeFile(
    join(channelAnalysisDir, ADVISOR_FILE),
    JSON.stringify(report, null, 2),
    "utf-8"
  );
  return report;
}
