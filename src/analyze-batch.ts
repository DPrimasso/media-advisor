import { existsSync } from "node:fs";
import { readdir, readFile, writeFile, mkdir } from "node:fs/promises";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { transcriptToPlainText } from "./save-transcript.js";
import { createOpenAIClient } from "./analyzer/openai-client.js";
import { createTranscriptClient } from "./transcript-client.js";
import { DIRS } from "./paths.js";
import type { TranscriptResponse } from "./transcript-client.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const defaultRoot = resolve(__dirname, "..");
const TRANSCRIPTS_DIR = join(defaultRoot, DIRS.transcripts);
const ANALYSIS_DIR = join(defaultRoot, DIRS.analysis);
const RATE_LIMIT_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function isValidTranscript(data: unknown): data is TranscriptResponse {
  if (!data || typeof data !== "object") return false;
  const d = data as Record<string, unknown>;
  return typeof d.video_id === "string" && d.transcript != null;
}

export interface BatchOptions {
  force?: boolean;
  transcriptsDir?: string;
  analysisDir?: string;
  transcriptApiKey?: string;
}

export async function runBatch(
  apiKey: string,
  options: BatchOptions = {}
): Promise<{ analyzed: number; skipped: number; failed: number }> {
  const transcriptsBase = options.transcriptsDir ?? TRANSCRIPTS_DIR;
  const analysisBase = options.analysisDir ?? ANALYSIS_DIR;
  const force = options.force ?? false;
  const transcriptClient = options.transcriptApiKey
    ? createTranscriptClient(options.transcriptApiKey)
    : null;
  const channelLatestCache = new Map<string, { videoId: string; published: string }[]>();

  const client = createOpenAIClient(apiKey);
  let analyzed = 0;
  let skipped = 0;
  let failed = 0;

  const channelDirs = await readdir(transcriptsBase, { withFileTypes: true });
  const toProcess: { channelId: string; filename: string }[] = [];

  for (const ent of channelDirs) {
    if (!ent.isDirectory()) continue;
    const channelDir = join(transcriptsBase, ent.name);
    const files = await readdir(channelDir);
    for (const f of files) {
      if (f.endsWith(".json")) toProcess.push({ channelId: ent.name, filename: f });
    }
  }

  for (const { channelId, filename } of toProcess) {
    const filepath = join(transcriptsBase, channelId, filename);

    let data: TranscriptResponse;
    try {
      const raw = await readFile(filepath, "utf-8");
      data = JSON.parse(raw) as TranscriptResponse;
    } catch (e) {
      console.error(`[${filename}] Invalid JSON:`, (e as Error).message);
      failed++;
      continue;
    }

    if (!isValidTranscript(data)) {
      console.error(`[${filename}] Invalid transcript: missing video_id or transcript`);
      failed++;
      continue;
    }

    const channelAnalysisDir = join(analysisBase, channelId);
    await mkdir(channelAnalysisDir, { recursive: true });
    const outputPath = join(channelAnalysisDir, `${data.video_id}.json`);
    if (!force && existsSync(outputPath)) {
      skipped++;
      continue;
    }

    try {
      const plainText = transcriptToPlainText(data);
      let metadata: { title?: string; author_name?: string; published_at?: string } | undefined;

      if (data.metadata) {
        metadata = {
          title: data.metadata.title,
          author_name: data.metadata.author_name,
        };
        if (transcriptClient && data.metadata.author_url) {
          let videos = channelLatestCache.get(data.metadata.author_url);
          if (!videos) {
            try {
              const latest = await transcriptClient.getChannelLatest(data.metadata.author_url);
              videos = latest.results.map((r) => ({ videoId: r.videoId, published: r.published }));
              channelLatestCache.set(data.metadata.author_url, videos);
              await sleep(200);
            } catch {
              // skip published_at
            }
          }
          const found = videos?.find((v) => v.videoId === data.video_id);
          if (found) metadata.published_at = found.published;
        }
      }

      const result = await client.analyzeTranscript(
        plainText,
        data.video_id,
        metadata
      );

      await writeFile(outputPath, JSON.stringify(result, null, 2), "utf-8");
      analyzed++;
    } catch (e) {
      console.error(`[${data.video_id}] Analysis failed:`, (e as Error).message);
      failed++;
      continue;
    }

    await sleep(RATE_LIMIT_MS);
  }

  return { analyzed, skipped, failed };
}
