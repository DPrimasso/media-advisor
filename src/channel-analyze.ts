import { createHash } from "node:crypto";
import { readFile, readdir, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { createChannelOpenAIClient } from "./analyzer/channel-openai.js";
import type { AnalysisResult } from "./analyzer/types.js";

const ANALYSIS_DIR = "analysis";
const CHANNELS_DIR = "channels";
const CHANNEL_ANALYSIS_FILE = "_channel.json";
const BATCH_SIZE = 20;
const RATE_LIMIT_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function normalizeTopic(t: string): string {
  return t
    .toLowerCase()
    .trim()
    .replace(/\s+/g, " ");
}

const TEMPORAL_PATTERNS =
  /\b(prossima|prossimo|domani|questa settimana|il prossimo|next match|prossima partita)\b/i;

/** Normalize v2 or baseline analysis to channel-analyze format */
function normalizeAnalysisForChannel(
  data: Record<string, unknown> & { video_id: string }
): AnalysisResult {
  const summary = (data.summary ?? data.summary_short ?? "") as string;
  const topicsRaw = data.topics ?? data.themes ?? [];
  const topics = (Array.isArray(topicsRaw) ? topicsRaw : []).map((t: { name?: string; theme?: string; relevance?: string; weight?: number }) => ({
    name: (t.name ?? t.theme ?? "") as string,
    relevance: (t.relevance ?? (t.weight && t.weight >= 20 ? "high" : t.weight && t.weight >= 10 ? "medium" : "low")) as "high" | "medium" | "low",
  }));
  const claimsRaw = data.claims ?? [];
  const claims = (Array.isArray(claimsRaw) ? claimsRaw : []).map((c: Record<string, unknown>) => {
    const pol = c.polarity ?? (c.stance === "POS" ? "positive" : c.stance === "NEG" ? "negative" : "neutral");
    return {
      ...c,
      topic: (c.topic ?? c.dimension ?? "") as string,
      subject: (c.subject ?? c.target_entity ?? undefined) as string | undefined,
      position: (c.position ?? c.claim_text ?? "") as string,
      polarity: pol as "positive" | "negative" | "neutral",
    };
  }) as NonNullable<AnalysisResult["claims"]>;
  return { video_id: data.video_id, analyzed_at: (data.analyzed_at as string) ?? new Date().toISOString(), metadata: data.metadata as AnalysisResult["metadata"], summary, topics, claims };
}

function isTemporalSensitive(positions: string[]): boolean {
  if (positions.length === 0) return false;
  const matches = positions.filter((p) => TEMPORAL_PATTERNS.test(p));
  return matches.length > positions.length / 2;
}

export interface ChannelAnalysis {
  channel_id: string;
  generated_at: string;
  input_hash: string;
  themes: { summary: string; main_topics: string[] };
  inconsistencies: { topic: string; subject?: string; description: string; videos: string[] }[];
  bias: { summary: string; patterns: { subject: string; description: string; supporting_claims?: string[] }[] };
}

export interface RunChannelAnalyzeOptions {
  channelsConfigPath?: string;
  channelId?: string;
  analysisDir?: string;
}

export async function runChannelAnalyze(
  apiKey: string,
  options: RunChannelAnalyzeOptions = {}
): Promise<{ channel_id: string; skipped: boolean; error?: string }[]> {
  const channelsPath = options.channelsConfigPath ?? join(process.cwd(), CHANNELS_DIR, "channels.json");
  const analysisDir = options.analysisDir ?? join(process.cwd(), ANALYSIS_DIR);

  const rawConfig = await readFile(channelsPath, "utf-8");
  const config = JSON.parse(rawConfig) as { channels: { id: string; name: string; order: number; video_list: string }[] };
  if (!config.channels?.length) return [];

  let channels = config.channels;
  if (options.channelId) {
    channels = channels.filter((c) => c.id === options.channelId);
    if (channels.length === 0) return [];
  }

  const client = createChannelOpenAIClient(apiKey);
  const results: { channel_id: string; skipped: boolean; error?: string }[] = [];

  for (const channel of channels) {
    const channelAnalysisDir = join(analysisDir, channel.id);
    if (!existsSync(channelAnalysisDir)) {
      results.push({ channel_id: channel.id, skipped: true });
      continue;
    }

    const files = (await readdir(channelAnalysisDir)).filter(
      (f) => f.endsWith(".json") && f !== CHANNEL_ANALYSIS_FILE
    );
    if (files.length === 0) {
      results.push({ channel_id: channel.id, skipped: true });
      continue;
    }

    const analyses: AnalysisResult[] = [];
    for (const f of files) {
      try {
        const raw = await readFile(join(channelAnalysisDir, f), "utf-8");
        const data = JSON.parse(raw) as Record<string, unknown> & { video_id: string };
        if (data.video_id && (data.summary || data.summary_short) && (data.topics || data.themes)) {
          const normalized = normalizeAnalysisForChannel(data);
          analyses.push(normalized);
        }
      } catch {
        // skip invalid files
      }
    }

    if (analyses.length === 0) {
      results.push({ channel_id: channel.id, skipped: true });
      continue;
    }

    const sorted = analyses.sort((a, b) => a.video_id.localeCompare(b.video_id));
    const hashInput = sorted
      .map((a) => `${a.video_id}:${a.analyzed_at ?? ""}`)
      .join("|");
    const inputHash = createHash("sha256").update(hashInput).digest("hex");

    const outputPath = join(channelAnalysisDir, CHANNEL_ANALYSIS_FILE);
    if (existsSync(outputPath)) {
      try {
        const existing = JSON.parse(await readFile(outputPath, "utf-8")) as ChannelAnalysis;
        if (existing.input_hash === inputHash) {
          results.push({ channel_id: channel.id, skipped: true });
          continue;
        }
      } catch {
        // overwrite
      }
    }

    try {
      const themes = await computeThemes(client, analyses);
      await sleep(RATE_LIMIT_MS);

      const inconsistencies = await computeInconsistencies(client, analyses);
      await sleep(RATE_LIMIT_MS);

      const bias = await computeBias(client, analyses);
      await sleep(RATE_LIMIT_MS);

      const output: ChannelAnalysis = {
        channel_id: channel.id,
        generated_at: new Date().toISOString(),
        input_hash: inputHash,
        themes,
        inconsistencies,
        bias,
      };

      await mkdir(channelAnalysisDir, { recursive: true });
      await writeFile(outputPath, JSON.stringify(output, null, 2), "utf-8");
      results.push({ channel_id: channel.id, skipped: false });
    } catch (e) {
      results.push({ channel_id: channel.id, skipped: false, error: (e as Error).message });
    }
  }

  return results;
}

async function computeThemes(
  client: ReturnType<typeof createChannelOpenAIClient>,
  analyses: AnalysisResult[]
): Promise<{ summary: string; main_topics: string[] }> {
  if (analyses.length <= BATCH_SIZE) {
    return client.analyzeThemes(
      analyses.map((a) => ({ video_id: a.video_id, summary: a.summary, topics: a.topics }))
    );
  }

  const batches: AnalysisResult[][] = [];
  for (let i = 0; i < analyses.length; i += BATCH_SIZE) {
    batches.push(analyses.slice(i, i + BATCH_SIZE));
  }

  const batchResults: { summary: string; main_topics: string[] }[] = [];
  for (const batch of batches) {
    const r = await client.analyzeThemes(
      batch.map((a) => ({ video_id: a.video_id, summary: a.summary, topics: a.topics }))
    );
    batchResults.push(r);
    await sleep(RATE_LIMIT_MS);
  }

  return client.analyzeThemes(
    batchResults.map((b, i) => ({
      video_id: `batch_${i}`,
      summary: b.summary,
      topics: b.main_topics.map((t) => ({ name: t, relevance: "high" })),
    }))
  );
}

async function computeInconsistencies(
  client: ReturnType<typeof createChannelOpenAIClient>,
  analyses: AnalysisResult[]
): Promise<{ topic: string; subject?: string; description: string; videos: string[] }[]> {
  const claimMap = new Map<
    string,
    { video_id: string; position: string; subject?: string }[]
  >();

  for (const a of analyses) {
    const claims = a.claims ?? [];
    for (const c of claims) {
      const topicNorm = normalizeTopic(c.topic);
      const subjectNorm = normalizeTopic(c.subject ?? "");
      const key = subjectNorm ? `${topicNorm}|${subjectNorm}` : topicNorm;
      if (!claimMap.has(key)) claimMap.set(key, []);
      claimMap.get(key)!.push({
        video_id: a.video_id,
        position: c.position,
        subject: c.subject,
      });
    }
  }

  const inconsistencies: { topic: string; subject?: string; description: string; videos: string[] }[] = [];

  for (const [key, claims] of claimMap) {
    const [topicPart, subjectPart] = key.includes("|") ? key.split("|") : [key, ""];
    const topic = topicPart;
    const subject = subjectPart || undefined;

    const byVideo = new Map<string, string[]>();
    for (const c of claims) {
      if (!byVideo.has(c.video_id)) byVideo.set(c.video_id, []);
      byVideo.get(c.video_id)!.push(c.position);
    }
    if (byVideo.size < 2) continue;

    const positions = claims.map((c) => c.position);
    if (isTemporalSensitive(positions)) continue;

    const analysisByVideo = new Map(analyses.map((a) => [a.video_id, a]));
    const enrichedClaims = claims
      .map((c) => {
        const a = analysisByVideo.get(c.video_id);
        return {
          video_id: c.video_id,
          position: c.position,
          subject: c.subject,
          published_at: a?.metadata?.published_at ?? a?.analyzed_at,
          summary: a?.summary,
        };
      })
      .sort((a, b) => (a.published_at ?? "").localeCompare(b.published_at ?? ""));
    const result = await client.checkInconsistency(topic, subject, enrichedClaims);
    if (result.has_contradiction && result.description) {
      inconsistencies.push({
        topic,
        subject,
        description: result.description,
        videos: [...new Set(claims.map((c) => c.video_id))],
      });
    }
    await sleep(RATE_LIMIT_MS);
  }

  return inconsistencies;
}

async function computeBias(
  client: ReturnType<typeof createChannelOpenAIClient>,
  analyses: AnalysisResult[]
): Promise<{ summary: string; patterns: { subject: string; description: string; supporting_claims?: string[] }[] }> {
  const claimsBySubject = new Map<string, { position: string; polarity?: string }[]>();

  for (const a of analyses) {
    const claims = a.claims ?? [];
    for (const c of claims) {
      const key = (c.subject ?? c.topic).trim() || "generale";
      const norm = normalizeTopic(key);
      if (!claimsBySubject.has(norm)) claimsBySubject.set(norm, []);
      claimsBySubject.get(norm)!.push({ position: c.position, polarity: c.polarity });
    }
  }

  if (claimsBySubject.size === 0) {
    return { summary: "Dati insufficienti per l'analisi dei bias.", patterns: [] };
  }

  const statsMap = new Map<
    string,
    { items: { position: string; polarity?: string }[]; stats: { positive: number; negative: number; neutral: number } }
  >();
  for (const [subject, items] of claimsBySubject) {
    const stats = { positive: 0, negative: 0, neutral: 0 };
    for (const i of items) {
      if (i.polarity === "positive") stats.positive++;
      else if (i.polarity === "negative") stats.negative++;
      else stats.neutral++;
    }
    statsMap.set(subject, { items, stats });
  }
  const obj = Object.fromEntries(statsMap);
  return client.analyzeBias(obj);
}
