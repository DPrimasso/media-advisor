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

export interface ChannelAnalysis {
  channel_id: string;
  generated_at: string;
  input_hash: string;
  themes: { summary: string; main_topics: string[] };
  inconsistencies: { topic: string; description: string; videos: string[] }[];
  bias: { summary: string; patterns: { subject: string; description: string }[] };
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
        const data = JSON.parse(raw) as AnalysisResult;
        if (data.video_id && data.summary && data.topics) {
          analyses.push(data);
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
): Promise<{ topic: string; description: string; videos: string[] }[]> {
  const claimMap = new Map<string, { video_id: string; position: string }[]>();

  for (const a of analyses) {
    const claims = a.claims ?? [];
    for (const c of claims) {
      const key = normalizeTopic(c.topic);
      if (!claimMap.has(key)) claimMap.set(key, []);
      claimMap.get(key)!.push({ video_id: a.video_id, position: c.position });
    }
  }

  const inconsistencies: { topic: string; description: string; videos: string[] }[] = [];

  for (const [topic, claims] of claimMap) {
    const byVideo = new Map<string, string[]>();
    for (const c of claims) {
      if (!byVideo.has(c.video_id)) byVideo.set(c.video_id, []);
      byVideo.get(c.video_id)!.push(c.position);
    }
    if (byVideo.size < 2) continue;

    const flatClaims = claims.map((c) => ({ video_id: c.video_id, position: c.position }));
    const result = await client.checkInconsistency(topic, flatClaims);
    if (result.has_contradiction && result.description) {
      inconsistencies.push({
        topic,
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
): Promise<{ summary: string; patterns: { subject: string; description: string }[] }> {
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

  const obj = Object.fromEntries(claimsBySubject);
  return client.analyzeBias(obj);
}
