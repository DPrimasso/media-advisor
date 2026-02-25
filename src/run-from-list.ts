import { readFile, writeFile, mkdir, appendFile, unlink } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { YoutubeTranscript } from "youtube-transcript";
import { createTranscriptClient } from "./transcript-client.js";
import { saveTranscript, transcriptToPlainText } from "./save-transcript.js";
import { createOpenAIClient } from "./analyzer/openai-client.js";
import { analyzeVideoV2 } from "./analyze-v2.js";
import { runChannelAnalyze } from "./channel-analyze.js";
import { generateChannelAdvisor } from "./channel-advisor.js";
import OpenAI from "openai";
import {
  transcriptPath,
  analysisPath,
  DIRS,
} from "./paths.js";
import { enrichWithPublishedAt } from "./video-metadata.js";
import type { TranscriptResponse } from "./transcript-client.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const CHANNELS_DIR = DIRS.channels;
const RATE_LIMIT_MS = 500;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function parseBooleanLike(value: string | undefined, fallback: boolean): boolean {
  if (!value) return fallback;
  const norm = value.trim().toLowerCase();
  if (["1", "true", "yes", "on"].includes(norm)) return true;
  if (["0", "false", "no", "off"].includes(norm)) return false;
  return fallback;
}

function parsePercentLike(value: string | undefined, fallback = 0): number {
  if (!value) return fallback;
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.min(100, Math.round(n)));
}

async function appendAdvisorRunLog(entry: Record<string, unknown>): Promise<void> {
  const logPath = join(root, DIRS.analysis, "_advisor_run_log.jsonl");
  const line = JSON.stringify({
    timestamp: new Date().toISOString(),
    ...entry,
  });
  await appendFile(logPath, `${line}\n`, "utf-8");
}

async function removeAdvisorFileIfExists(channelAnalysisDir: string): Promise<void> {
  const advisorPath = join(channelAnalysisDir, "_advisor.json");
  if (!existsSync(advisorPath)) return;
  try {
    await unlink(advisorPath);
  } catch {
    // best effort cleanup
  }
}

function extractVideoId(urlOrId: string): string | null {
  const match = urlOrId.match(/(?:v=)([a-zA-Z0-9_-]{11})/);
  return match ? match[1] : urlOrId.length === 11 ? urlOrId : null;
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
  /** Use v2 pipeline (claims with evidence_quotes, timestamp) */
  useV2?: boolean;
  advisorEnabled?: boolean;
  advisorPredictionEnabled?: boolean;
  advisorMinFidelity?: number;
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
  const useV2 = options.useV2 ?? true;
  const advisorEnabled = options.advisorEnabled ?? parseBooleanLike(process.env.ADVISOR_ENABLED, true);
  const advisorPredictionEnabled =
    options.advisorPredictionEnabled ??
    parseBooleanLike(process.env.ADVISOR_PREDICTION_ENABLED, true);
  const advisorMinFidelity =
    options.advisorMinFidelity ?? parsePercentLike(process.env.ADVISOR_MIN_FIDELITY, 0);

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
  const openai = new OpenAI({ apiKey: openaiApiKey });
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

    const total = urls.length;
    let processed = 0;
    for (const url of urls) {
      processed++;
      if (processed % 10 === 0 || processed === total) {
        console.log(`[${channel.id}] ${processed}/${total} videos...`);
      }
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
          await enrichWithPublishedAt(data, {
            getChannelLatest: async (authorUrl) => {
              const cached = channelLatestCache.get(authorUrl);
              if (cached) return cached;
              const latest = await transcriptClient.getChannelLatest(authorUrl);
              const videos = latest.results.map((r) => ({ videoId: r.videoId, published: r.published }));
              channelLatestCache.set(authorUrl, videos);
              return videos;
            },
          });
          await saveTranscript(data, channelTranscriptsDir);
          transcriptsFetched++;
        } catch {
          try {
            await sleep(1500); // YouTube throttles; pace fallback requests
            const ytSegments = await YoutubeTranscript.fetchTranscript(videoId);
            data = {
              video_id: videoId,
              language: ytSegments[0]?.lang ?? "it",
              transcript: ytSegments.map((s) => ({
                text: s.text,
                start: s.offset,
                duration: s.duration,
              })),
            };
            await enrichWithPublishedAt(data);
            await saveTranscript(data, channelTranscriptsDir);
            transcriptsFetched++;
            console.log(`[${videoId}] ✓ fallback (youtube-transcript)`);
          } catch (e2) {
            console.error(`[${videoId}] Transcript fetch failed:`, (e2 as Error).message);
            failed++;
            continue;
          }
        }
        await sleep(RATE_LIMIT_MS);
      }

      const analysisFilePath = analysisPath(root, channel.id, videoId);
      if (!forceAnalyze && existsSync(analysisFilePath)) {
        skipped++;
        continue;
      }

      try {
        const hadPublished = !!data.metadata?.published_at;
        await enrichWithPublishedAt(data, {
          getChannelLatest: async (authorUrl) => {
            let videos = channelLatestCache.get(authorUrl);
            if (!videos) {
              const latest = await transcriptClient.getChannelLatest(authorUrl);
              videos = latest.results.map((r) => ({ videoId: r.videoId, published: r.published }));
              channelLatestCache.set(authorUrl, videos);
            }
            return videos ?? [];
          },
        });
        if (existsSync(transcriptFilePath) && !hadPublished && data.metadata?.published_at) {
          await saveTranscript(data, channelTranscriptsDir);
        }
        const metadata = data.metadata
          ? {
              title: data.metadata.title,
              author_name: data.metadata.author_name,
              published_at: data.metadata.published_at,
            }
          : undefined;
        const result = useV2
          ? await analyzeVideoV2({
              openai,
              data,
              videoId,
              channelId: channel.id,
              metadata: { title: metadata?.title, published_at: metadata?.published_at },
            })
          : await openaiClient.analyzeTranscript(transcriptToPlainText(data), videoId, metadata);
        await writeFile(analysisFilePath, JSON.stringify(result, null, 2), "utf-8");
        analyzed++;
        console.log(`[${channel.id}] ✓ ${videoId} (${processed}/${total})`);
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

    if (advisorEnabled) {
      try {
        const advisor = await generateChannelAdvisor(channel.id, channelAnalysisDir, {
          predictionEnabled: advisorPredictionEnabled,
          minFidelity: advisorMinFidelity,
        });
        if (advisor) {
          console.log(
            `[${channel.id}] Advisor score ${advisor.scores.advisor_score} (claims ${advisor.claims_analyzed}, prediction ${
              advisorPredictionEnabled ? "on" : "off"
            })`
          );
          await appendAdvisorRunLog({
            channel_id: channel.id,
            advisor_enabled: true,
            prediction_enabled: advisorPredictionEnabled,
            min_fidelity: advisorMinFidelity,
            status: "generated",
            advisor_score: advisor.scores.advisor_score,
            evidence_fidelity: advisor.scores.evidence_fidelity,
            claims_analyzed: advisor.claims_analyzed,
          });
        } else {
          console.log(
            `[${channel.id}] Advisor skipped (min_fidelity=${advisorMinFidelity} not met or no eligible data)`
          );
          await appendAdvisorRunLog({
            channel_id: channel.id,
            advisor_enabled: true,
            prediction_enabled: advisorPredictionEnabled,
            min_fidelity: advisorMinFidelity,
            status: "skipped",
          });
        }
      } catch (e) {
        console.error(`[${channel.id}] Advisor generation failed:`, (e as Error).message);
        await appendAdvisorRunLog({
          channel_id: channel.id,
          advisor_enabled: true,
          prediction_enabled: advisorPredictionEnabled,
          min_fidelity: advisorMinFidelity,
          status: "failed",
          error: (e as Error).message,
        });
      }
    } else {
      await removeAdvisorFileIfExists(channelAnalysisDir);
      console.log(`[${channel.id}] Advisor disabled via ADVISOR_ENABLED/option`);
      await appendAdvisorRunLog({
        channel_id: channel.id,
        advisor_enabled: false,
        prediction_enabled: advisorPredictionEnabled,
        min_fidelity: advisorMinFidelity,
        status: "disabled",
      });
    }
  }

  return { channels: results };
}
