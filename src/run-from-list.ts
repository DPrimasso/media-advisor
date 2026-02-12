import { readFile, writeFile, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createTranscriptClient } from "./transcript-client.js";
import { saveTranscript, transcriptToPlainText } from "./save-transcript.js";
import { createOpenAIClient } from "./analyzer/openai-client.js";
import { runChannelAnalyze } from "./channel-analyze.js";
import {
  transcriptPath,
  analysisPath,
  DIRS,
} from "./paths.js";
import type { TranscriptResponse } from "./transcript-client.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const CHANNELS_DIR = DIRS.channels;
const RATE_LIMIT_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function extractVideoId(urlOrId: string): string | null {
  const match = urlOrId.match(/(?:v=)([a-zA-Z0-9_-]{11})/);
  return match ? match[1] : urlOrId.length === 11 ? urlOrId : null;
}

/** Estrae la data dal titolo quando in formato DD/MM/YY o simile (es. "PUNTO CHIARO 11/02/26") */
function parseDateFromTitle(title: string): string | null {
  const m = title.match(/(\d{1,2})\/(\d{1,2})\/(\d{2,4})/);
  if (!m) return null;
  const [, d, month, y] = m;
  const year = y.length === 2 ? `20${y}` : y;
  return `${year}-${month.padStart(2, "0")}-${d.padStart(2, "0")}T12:00:00+00:00`;
}

export interface ChannelConfig {
  id: string;
  name: string;
  order: number;
  video_list: string;
}

export interface ChannelsConfig {
  channels: ChannelConfig[];
}

export interface RunFromListOptions {
  channelsConfigPath?: string;
  channelId?: string; // process only this channel
  forceTranscript?: boolean;
  forceAnalyze?: boolean;
  skipChannelAnalysis?: boolean;
}

export interface RunFromListResult {
  channels: { id: string; transcriptsFetched: number; analyzed: number; skipped: number; failed: number }[];
}

export async function runFromList(
  transcriptApiKey: string,
  openaiApiKey: string,
  options: RunFromListOptions = {}
): Promise<RunFromListResult> {
  const channelsPath = options.channelsConfigPath ?? join(root, CHANNELS_DIR, "channels.json");
  const forceTranscript = options.forceTranscript ?? false;
  const forceAnalyze = options.forceAnalyze ?? false;

  const rawConfig = await readFile(channelsPath, "utf-8");
  const config = JSON.parse(rawConfig) as ChannelsConfig;
  if (!config.channels || !Array.isArray(config.channels)) {
    throw new Error("channels.json must have a 'channels' array");
  }

  let channels = config.channels.sort((a, b) => a.order - b.order);
  if (options.channelId) {
    channels = channels.filter((c) => c.id === options.channelId);
    if (channels.length === 0) throw new Error(`Channel ${options.channelId} not found`);
  }

  const transcriptClient = createTranscriptClient(transcriptApiKey);
  const openaiClient = createOpenAIClient(openaiApiKey);
  const channelLatestCache = new Map<string, { videoId: string; published: string }[]>();
  const results: RunFromListResult["channels"] = [];

  for (const channel of channels) {
    const listPath = join(root, CHANNELS_DIR, channel.video_list);
    const raw = await readFile(listPath, "utf-8");
    const urls = JSON.parse(raw) as string[];
    if (!Array.isArray(urls) || urls.some((u) => typeof u !== "string")) {
      console.error(`[${channel.id}] Invalid video list in ${channel.video_list}`);
      results.push({ id: channel.id, transcriptsFetched: 0, analyzed: 0, skipped: 0, failed: urls?.length ?? 0 });
      continue;
    }

    const channelTranscriptsDir = join(root, DIRS.transcripts, channel.id);
    const channelAnalysisDir = join(root, DIRS.analysis, channel.id);
    await mkdir(channelTranscriptsDir, { recursive: true });
    await mkdir(channelAnalysisDir, { recursive: true });

    let transcriptsFetched = 0;
    let analyzed = 0;
    let skipped = 0;
    let failed = 0;

    for (const url of urls) {
      const videoId = extractVideoId(url);
      if (!videoId) {
        console.error(`[${url}] Invalid URL or video ID`);
        failed++;
        continue;
      }

      const transcriptFilePath = transcriptPath(root, channel.id, videoId);
      let data: TranscriptResponse;

      if (!forceTranscript && existsSync(transcriptFilePath)) {
        const rawData = await readFile(transcriptFilePath, "utf-8");
        data = JSON.parse(rawData) as TranscriptResponse;
      } else {
        try {
          data = await transcriptClient.getTranscript(url, {
            format: "json",
            include_timestamp: true,
            send_metadata: true,
          });
          await saveTranscript(data, channelTranscriptsDir);
          transcriptsFetched++;
        } catch (e) {
          console.error(`[${videoId}] Transcript fetch failed:`, (e as Error).message);
          failed++;
          continue;
        }
        await sleep(RATE_LIMIT_MS);
      }

      const analysisFilePath = analysisPath(root, channel.id, videoId);
      if (!forceAnalyze && existsSync(analysisFilePath)) {
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
          if (data.metadata.author_url) {
            let videos = channelLatestCache.get(data.metadata.author_url);
            if (!videos) {
              try {
                const latest = await transcriptClient.getChannelLatest(data.metadata.author_url);
                videos = latest.results.map((r) => ({ videoId: r.videoId, published: r.published }));
                channelLatestCache.set(data.metadata.author_url, videos);
                await sleep(200);
              } catch {
                // channel/latest failed, skip published_at
              }
            }
            const found = videos?.find((v) => v.videoId === videoId);
            if (found) metadata.published_at = found.published;
            else if (data.metadata.title) {
              const fromTitle = parseDateFromTitle(data.metadata.title);
              if (fromTitle) metadata.published_at = fromTitle;
            }
          }
        }

        const result = await openaiClient.analyzeTranscript(plainText, videoId, metadata);
        await writeFile(analysisFilePath, JSON.stringify(result, null, 2), "utf-8");
        analyzed++;
      } catch (e) {
        console.error(`[${videoId}] Analysis failed:`, (e as Error).message);
        failed++;
        continue;
      }

      await sleep(RATE_LIMIT_MS);
    }

    results.push({ id: channel.id, transcriptsFetched, analyzed, skipped, failed });

    if (!options.skipChannelAnalysis) {
      try {
        const channelResults = await runChannelAnalyze(openaiApiKey, {
          channelsConfigPath: channelsPath,
          channelId: channel.id,
        });
        for (const r of channelResults) {
          if (r.error) console.error(`[${r.channel_id}] Channel analysis failed:`, r.error);
        }
      } catch (e) {
        console.error(`[${channel.id}] Channel analysis failed:`, (e as Error).message);
      }
    }
  }

  return { channels: results };
}
